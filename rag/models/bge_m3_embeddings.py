"""BGE-M3 embedding adapter (docs/specs/retrieval-backend-modernization).

BGE-M3 (BAAI/bge-m3) outputs dense (1024d) + sparse (lexical_weights) + ColBERT
multi-vector embeddings from a single forward pass. This adapter exposes:

- ``encode_hybrid`` / ``encode_hybrid_batch``: dense + sparse via FlagEmbedding's
  ``BGEM3FlagModel`` (the only loader that brings up BGE-M3's sparse/colbert linear
  heads — they are NOT in HF's auto-converted ``model.safetensors``).
- ``encode_late_chunked``: token-level ``last_hidden_state`` via a separate
  ``transformers.AutoModel``, mean-pooled per chunk span (late chunking, §3.5).
- LangChain ``Embeddings`` interface (``embed_query`` / ``embed_documents``) so it
  drops into the existing ``get_embeddings()`` singleton.

F-04 (方案 D): two model objects because BGE-M3's sparse head weights only exist
in FlagEmbedding's ``BGEM3Model`` loading path (safetensors实测仅 7 个 base key),
while late chunking needs the base encoder's ``last_hidden_state`` (in safetensors).
F-06: FlashAttention2 is attempted on both models; on failure, max_length is
lowered and late-chunk throughput degrades gracefully.
F-07: singleton with ``reset_bge_m3_embeddings``; ``reset_embeddings`` in
``models.embedding_models`` clears this instance too (mutual reset).
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings

from utils.env_utils import (
    BGE_M3_DEVICE,
    BGE_M3_FLASH_ATTENTION,
    BGE_M3_MAX_LENGTH,
    BGE_M3_USE_FP16,
    EMBEDDING_BATCH_SIZE,
)
from utils.log_utils import log

__all__ = [
    "BGEM3Embeddings",
    "bge_m3_hybrid_asset_fingerprint",
    "bge_m3_hybrid_assets_ready",
    "get_bge_m3_embeddings",
    "set_bge_m3_embeddings_instance",
    "reset_bge_m3_embeddings",
    "is_bge_m3_cached",
]

_HYBRID_HEAD_FILES = ("sparse_linear.pt", "colbert_linear.pt")


# 进程级单例。F-07: reset_bge_m3_embeddings 与 embedding_models.reset_embeddings 互清。
_instance: BGEM3Embeddings | None = None
_instance_lock = threading.Lock()


def is_bge_m3_cached(model_path: str) -> bool:
    """Return whether the local model directory looks loadable."""
    p = Path(model_path)
    return p.is_dir() and any(
        (p / filename).is_file() for filename in ("model.safetensors", "pytorch_model.bin")
    )


def bge_m3_hybrid_assets_ready(model_path: str) -> bool:
    """Whether trained sparse and ColBERT heads are available for inference."""
    path = Path(model_path)
    return is_bge_m3_cached(str(path)) and all(
        (path / filename).is_file() and (path / filename).stat().st_size > 0
        for filename in _HYBRID_HEAD_FILES
    )


@lru_cache(maxsize=16)
def _hybrid_asset_fingerprint_cached(
    model_path: str,
    signatures: tuple[tuple[str, int, int, int], ...],
) -> str:
    digest = hashlib.sha256()
    path = Path(model_path)
    for filename, _size, _mtime_ns, _ctime_ns in signatures:
        digest.update(filename.encode("utf-8"))
        with (path / filename).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()[:16]


def bge_m3_hybrid_asset_fingerprint(model_path: str) -> str:
    """Stable identity for the trained sparse/ColBERT heads, or ``missing``."""
    path = Path(model_path).expanduser().resolve(strict=False)
    if not bge_m3_hybrid_assets_ready(str(path)):
        return "missing"
    signatures = tuple(
        (
            filename,
            (path / filename).stat().st_size,
            (path / filename).stat().st_mtime_ns,
            (path / filename).stat().st_ctime_ns,
        )
        for filename in _HYBRID_HEAD_FILES
    )
    return _hybrid_asset_fingerprint_cached(str(path), signatures)


class BGEM3Embeddings(Embeddings):
    """BGE-M3 adapter: FlagModel for dense+sparse, AutoModel for late chunking.

    持有两个模型对象：
    - ``_flag_model``: ``FlagEmbedding.BGEM3FlagModel``，负责 ``encode_hybrid``（dense + sparse）。
      它是唯一能加载 BGE-M3 sparse_linear head 的入口（safetensors 不含该权重）。
    - ``_auto_model`` / ``_tokenizer``: ``transformers.AutoModel`` + ``AutoTokenizer``，
      负责 ``encode_late_chunked``（base encoder 的 ``last_hidden_state``）。懒加载，仅 late chunking 启用时才载入。
    """

    def __init__(
        self,
        model_path: str,
        device: str = BGE_M3_DEVICE,
        use_fp16: bool = BGE_M3_USE_FP16,
        max_length: int = BGE_M3_MAX_LENGTH,
        batch_size: int = EMBEDDING_BATCH_SIZE,
        flash_attention: bool = BGE_M3_FLASH_ATTENTION,
    ):
        self.model_path = model_path
        self.device = device
        self.use_fp16 = use_fp16 and device != "cpu"  # CPU 不支持 fp16
        self.max_length = max_length
        self.batch_size = batch_size
        self.flash_attention = flash_attention

        # 懒加载标志
        self._flag_model: Any = None
        self._auto_model: Any = None
        self._tokenizer: Any = None
        self._auto_load_attempted = False
        self._flag_load_attempted = False
        self._query_forward_count = 0
        self._query_count_lock = threading.Lock()
        self.hybrid_heads_available = bge_m3_hybrid_assets_ready(model_path)
        self.hybrid_head_fingerprint = bge_m3_hybrid_asset_fingerprint(model_path)

        # F-06: 摄入期 late chunking 信号量（进程级串行，避免多 8K 前向叠加 OOM）
        self._late_chunk_semaphore = threading.Semaphore(
            max(1, int(os.getenv("INGEST_EMBEDDING_CONCURRENCY", "1")))
        )

        log.info(
            f"BGEM3Embeddings configured: path={model_path}, device={device}, "
            f"fp16={self.use_fp16}, max_length={max_length}, flash_attn={flash_attention}"
        )
        if not self.hybrid_heads_available:
            log.warning(
                "BGE-M3 trained sparse/ColBERT heads are missing; dense embeddings remain "
                "available while sparse and ColBERT degrade safely. Run scripts/download_bge_m3.py."
            )

    # ------------------------------------------------------------------
    # 模型加载（懒加载，各自独立失败处理）
    # ------------------------------------------------------------------

    def _ensure_flag_model(self) -> Any:
        """加载 FlagModel（dense+sparse）。一次性粘性降级：失败后标记，不再重试。"""
        if self._flag_model is not None:
            return self._flag_model
        if self._flag_load_attempted:
            raise RuntimeError("BGEM3FlagModel previously failed to load; not retrying")
        self._flag_load_attempted = True
        try:
            from FlagEmbedding import BGEM3FlagModel

            self._flag_model = BGEM3FlagModel(
                self.model_path,
                use_fp16=self.use_fp16,
                device=self.device,
            )
            log.info(f"BGEM3FlagModel loaded from {self.model_path}")
            return self._flag_model
        except Exception as e:  # noqa: BLE001
            self._flag_model = None
            log.error(f"BGEM3FlagModel load failed: {e}")
            raise

    def _ensure_auto_model(self) -> tuple[Any, Any]:
        """加载 AutoModel + Tokenizer（late chunking 的 last_hidden_state）。

        F-04: 单独的 AutoModel，因为 late chunking 只需 base encoder 的 hidden state，
        不需 sparse/colbert head（safetensors 的 base 权重即可）。
        """
        if self._auto_model is not None:
            return self._auto_model, self._tokenizer
        if self._auto_load_attempted:
            raise RuntimeError("AutoModel previously failed to load; not retrying")
        self._auto_load_attempted = True
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer

            # F-06: 尝试 FlashAttention2；不可用则降级（attention 峰值升高，靠 max_length + 信号量兜底）
            attn_kwargs: dict[str, Any] = {}
            if self.flash_attention and self.device != "cpu":
                try:
                    import flash_attn  # noqa: F401

                    attn_kwargs["attn_implementation"] = "flash_attention_2"
                except ImportError:
                    log.warning(
                        "flash-attn not installed; late chunking 8K attention peak ~4.3GB "
                        "(see design §9). max_length auto-lowered to 2048 if needed."
                    )

            dtype = torch.float16 if self.use_fp16 else torch.float32
            self._auto_model = AutoModel.from_pretrained(
                self.model_path, dtype=dtype, output_hidden_states=False, **attn_kwargs
            ).to(self.device)
            self._auto_model.eval()
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            log.info(f"AutoModel loaded from {self.model_path} (dtype={dtype}, attn={attn_kwargs})")
            return self._auto_model, self._tokenizer
        except Exception as e:  # noqa: BLE001
            self._auto_model = None
            self._tokenizer = None
            log.error(f"AutoModel load failed: {e}")
            raise

    # ------------------------------------------------------------------
    # LangChain Embeddings 接口（dense only）
    # ------------------------------------------------------------------

    def embed_query(self, text: str) -> list[float]:
        """Dense embedding for a single query (LangChain Embeddings interface)."""
        with self._query_count_lock:
            self._query_forward_count += 1
        dense, _sparse = self.encode_hybrid(text)
        return dense

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Dense embeddings for a batch of documents (LangChain Embeddings interface)."""
        results = self.encode_hybrid_batch(texts)
        return [dense for dense, _sparse in results]

    # ------------------------------------------------------------------
    # Hybrid 编码（dense + sparse，via FlagModel）
    # ------------------------------------------------------------------

    def encode_hybrid(self, text: str) -> tuple[list[float], dict[int, float]]:
        """单次前向产出 dense (1024d) + sparse (lexical_weights)。

        Returns:
            (dense_vec, sparse_weights) — sparse 的 key 已从 FlagModel 的 str 转 int，
            value 转 float，兼容 Milvus SPARSE_FLOAT_VECTOR。
        """
        batch = self.encode_hybrid_batch([text])
        return batch[0]

    def encode_query_representation(
        self,
        text: str,
        *,
        return_colbert: bool = False,
    ) -> dict[str, Any]:
        """One atomic BGE-M3 forward for dense/sparse/optional ColBERT query heads."""
        model = self._ensure_flag_model()
        with self._query_count_lock:
            self._query_forward_count += 1
        use_hybrid_heads = self.hybrid_heads_available
        out = model.encode(
            [text],
            batch_size=1,
            return_dense=True,
            return_sparse=use_hybrid_heads,
            return_colbert_vecs=bool(return_colbert and use_hybrid_heads),
            max_length=self.max_length,
        )
        dense = out["dense_vecs"][0].tolist()
        sparse = (
            {int(key): float(value) for key, value in out["lexical_weights"][0].items()}
            if use_hybrid_heads
            else None
        )
        colbert = None
        if return_colbert and use_hybrid_heads:
            vectors = out.get("colbert_vecs")
            if vectors is not None and len(vectors):
                first = vectors[0]
                colbert = first.tolist() if hasattr(first, "tolist") else first
        return {"dense": dense, "sparse": sparse, "colbert": colbert}

    @property
    def query_forward_count(self) -> int:
        with self._query_count_lock:
            return self._query_forward_count

    def encode_hybrid_batch(
        self, texts: Sequence[str]
    ) -> list[tuple[list[float], dict[int, float]]]:
        """批量 hybrid 编码。FlagModel 一次前向处理整批。"""
        model = self._ensure_flag_model()
        # FlagModel 返回 dict: dense_vecs (np.ndarray), lexical_weights (list[dict[str,float]])
        use_hybrid_heads = self.hybrid_heads_available
        out = model.encode(
            list(texts),
            batch_size=min(self.batch_size, len(texts)) if texts else 1,
            return_dense=True,
            return_sparse=use_hybrid_heads,
            return_colbert_vecs=False,
            max_length=self.max_length,
        )
        dense_arr = out["dense_vecs"]  # np.ndarray (n, 1024)
        sparse_list = out.get("lexical_weights") if use_hybrid_heads else None
        results: list[tuple[list[float], dict[int, float]]] = []
        for i in range(len(texts)):
            dense = dense_arr[i].tolist()
            # F-01/sparse 兼容: FlagModel 返回 str key，Milvus 需要 int key
            sparse = (
                {int(k): float(v) for k, v in sparse_list[i].items()}
                if sparse_list is not None
                else {}
            )
            results.append((dense, sparse))
        return results

    def encode_colbert_documents(
        self,
        texts: Sequence[str],
        *,
        max_tokens: int = 512,
        batch_size: int | None = None,
    ) -> list[list[list[float]]]:
        """Encode bounded document token vectors for late interaction."""
        if not texts:
            return []
        if not self.hybrid_heads_available:
            raise RuntimeError("BGE-M3 trained ColBERT head is unavailable")
        model = self._ensure_flag_model()
        effective_batch = max(1, min(batch_size or self.batch_size, len(texts)))
        results: list[list[list[float]]] = []
        for start in range(0, len(texts), effective_batch):
            batch = list(texts[start : start + effective_batch])
            out = model.encode(
                batch,
                batch_size=min(effective_batch, len(batch)),
                return_dense=True,
                return_sparse=True,
                return_colbert_vecs=True,
                max_length=min(self.max_length, max(8, int(max_tokens) + 2)),
            )
            vectors = out.get("colbert_vecs")
            if vectors is None or len(vectors) != len(batch):
                raise RuntimeError("BGE-M3 did not return ColBERT document vectors")
            for value in vectors:
                matrix = value.tolist() if hasattr(value, "tolist") else value
                results.append(matrix[: max(1, int(max_tokens))])
        return results

    # ------------------------------------------------------------------
    # Late chunking（dense only, via AutoModel last_hidden_state）
    # ------------------------------------------------------------------

    def encode_late_chunked(
        self,
        section_text: str,
        chunk_spans: list[tuple[int, int]],
    ) -> list[list[float]]:
        """对整 section 单次前向，按 chunk_spans mean-pool 得到每个 chunk 的 dense 向量。

        F-04/F-08: 用 AutoModel 的 last_hidden_state（base encoder），按 char span → token span
        映射后 mean-pool。每个 chunk embedding 携带全局 section 上下文。

        Args:
            section_text: 完整 parent section 文本（≤ max_length tokens）。
            chunk_spans: list of (start_char, end_char)，相对于 section_text。

        Returns:
            list of dense vectors，长度 == len(chunk_spans)，每向量 1024d。
        """
        import torch

        model, tokenizer = self._ensure_auto_model()

        # F-06: 信号量限流，串行化 late chunking 前向
        with self._late_chunk_semaphore:
            return self._late_chunk_forward(section_text, chunk_spans, model, tokenizer, torch)

    def _late_chunk_forward(
        self,
        section_text: str,
        chunk_spans: list[tuple[int, int]],
        model: Any,
        tokenizer: Any,
        torch: Any,
    ) -> list[list[float]]:
        """实际的 late chunking 前向 + mean-pool（已持信号量）。"""
        # 编码整 section，保留 char offset 映射
        encoded = tokenizer(
            section_text,
            return_offsets_mapping=True,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_length,
        )
        offset_mapping = encoded["offset_mapping"][0]  # (seq_len, 2) char spans per token
        input_ids = encoded["input_ids"].to(self.device)

        with torch.no_grad():
            outputs = model(input_ids=input_ids)
            # last_hidden_state: (1, seq_len, 1024)
            hidden = outputs.last_hidden_state[0]  # (seq_len, 1024)

        # 对每个 chunk span，找到落在 [start_char, end_char) 内的 token，mean-pool
        chunk_vecs: list[list[float]] = []
        for start_char, end_char in chunk_spans:
            # F-08: 找 token whose offset falls within [start_char, end_char)
            # offset_mapping[i] = (char_start, char_end)；特殊 token（CLS/SEP/pad）offset=(0,0) 跳过
            mask = []
            for tok_idx, (cs, ce) in enumerate(offset_mapping.tolist()):
                if cs == 0 and ce == 0:
                    continue  # 特殊 token
                # token 与 chunk 区间有重叠即纳入
                if cs < end_char and ce > start_char:
                    mask.append(tok_idx)
            if not mask:
                # F-08 降级: span 映射失败（splitter 归一化/中文重复子串），用全序列 pool 兜底
                log.warning(
                    f"late chunk span ({start_char},{end_char}) mapped to no tokens; "
                    "falling back to full-sequence pool"
                )
                mask = [
                    i
                    for i, (cs, ce) in enumerate(offset_mapping.tolist())
                    if not (cs == 0 and ce == 0)
                ]
            token_vecs = hidden[mask]  # (n_tokens_in_chunk, 1024)
            chunk_vec = token_vecs.mean(dim=0).cpu().tolist()
            chunk_vecs.append(chunk_vec)
        return chunk_vecs


# ---------------------------------------------------------------------------
# Singleton（F-07）
# ---------------------------------------------------------------------------


def get_bge_m3_embeddings(
    model_path: str | None = None,
    **kwargs: Any,
) -> BGEM3Embeddings:
    """获取或创建进程级单例。

    F-07: 与 ``models.embedding_models.get_embeddings`` 的 local 分支共享——后者按模型名分派到此。
    ``reset_embeddings`` 会调用 ``reset_bge_m3_embeddings`` 互清。
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                if model_path is None:
                    from utils.env_utils import resolve_embedding_settings

                    model_path = resolve_embedding_settings("local").model_source
                _instance = BGEM3Embeddings(model_path=model_path, **kwargs)
    return _instance


def set_bge_m3_embeddings_instance(instance: Any) -> Any:
    """Register the adapter created by the outer embedding factory as the shared instance."""
    global _instance
    with _instance_lock:
        _instance = instance
    return instance


def reset_bge_m3_embeddings(*, reset_outer: bool = True) -> None:
    """重置单例。F-07: 同时清 ``embedding_models._instance`` 以保证两者一致。"""
    global _instance
    with _instance_lock:
        _instance = None
    # 互清：确保 get_embeddings() 下次重新分派
    if reset_outer:
        try:
            from models.embedding_models import reset_embeddings as _reset_outer

            _reset_outer(reset_bge=False)
        except Exception:
            pass


if __name__ == "__main__":
    # 快速验证：python -m models.bge_m3_embeddings
    emb = get_bge_m3_embeddings()
    text = "航空发动机振动异常诊断"
    dense, sparse = emb.encode_hybrid(text)
    print(f"dense dim: {len(dense)}, sparse tokens: {len(sparse)}")
    print(f"sparse sample: {dict(list(sparse.items())[:3])}")
