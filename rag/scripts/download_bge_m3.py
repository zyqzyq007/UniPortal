#!/usr/bin/env python3
"""Download and save the BGE-M3 embedding model for offline use.

BGE-M3 (BAAI/bge-m3) outputs dense (1024d) + sparse (lexical_weights) + ColBERT
multi-vector embeddings from a single forward pass. This script saves the full
HF model (AutoModel + tokenizer + sparse linear head) so air-gapped deploys load
from disk instead of hitting Hugging Face (REQ-RBM-009).

F-06: FlashAttention2 (``flash-attn``) is a runtime dependency, not a model
artifact — it must be pre-installed/wheel-prepacked separately. This script
prints a reminder if ``flash-attn`` is not importable.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.env_utils import PROJECT_ROOT

DEFAULT_MODEL = "BAAI/bge-m3"
DEFAULT_OUTPUT = str(PROJECT_ROOT / "models" / "local_models" / "bge-m3")
REQUIRED_HYBRID_HEADS = ("sparse_linear.pt", "colbert_linear.pt")


def _safe_model_name(model_name: str) -> str:
    return model_name.replace("/", "_").replace(":", "_")


def missing_required_assets(output: Path) -> tuple[str, ...]:
    missing: list[str] = []
    if not (output / "config.json").is_file():
        missing.append("config.json")
    if not any(
        (output / filename).is_file() for filename in ("model.safetensors", "pytorch_model.bin")
    ):
        missing.append("model.safetensors|pytorch_model.bin")
    missing.extend(
        filename
        for filename in REQUIRED_HYBRID_HEADS
        if not (output / filename).is_file() or (output / filename).stat().st_size <= 0
    )
    return tuple(missing)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL, help="HuggingFace model ID to download.")
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="Directory to save the model for offline loading.",
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("HF_ENDPOINT", "https://hf-mirror.com"),
        help="HuggingFace endpoint (default: hf-mirror.com for CN; set HF_ENDPOINT to override).",
    )
    args = parser.parse_args()

    output = Path(args.output).expanduser()
    if not output.is_absolute():
        output = PROJECT_ROOT / output

    # Use the configured endpoint (CN mirror by default, AGENTS.md §5 mirror strategy).
    os.environ.setdefault("HF_ENDPOINT", args.endpoint)

    # Lazy import so ``--help`` works without local-model dependencies installed.
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        print(f"ERROR: huggingface_hub not installed: {exc}", file=sys.stderr)
        print("Run: uv sync --extra local-models", file=sys.stderr)
        return 1

    print(f"Downloading {args.model} → {output} (endpoint={os.environ['HF_ENDPOINT']}) ...")
    output.mkdir(parents=True, exist_ok=True)
    allow_patterns = [
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "sentencepiece.bpe.model",
        *REQUIRED_HYBRID_HEADS,
    ]
    if not any(
        (output / filename).is_file() for filename in ("model.safetensors", "pytorch_model.bin")
    ):
        allow_patterns.extend(("model.safetensors", "pytorch_model.bin"))
    snapshot_download(
        repo_id=args.model,
        local_dir=str(output),
        endpoint=os.environ["HF_ENDPOINT"],
        allow_patterns=allow_patterns,
        ignore_patterns=["*.msgpack", "*.h5", "*.ot"],
    )
    missing = missing_required_assets(output)
    if missing:
        print(
            f"ERROR: incomplete BGE-M3 snapshot; missing {', '.join(missing)}",
            file=sys.stderr,
        )
        return 2

    # FlashAttention2 reminder (F-06): runtime dep, not a model artifact.
    try:
        import flash_attn  # noqa: F401

        fa_status = "installed"
    except ImportError:
        fa_status = "NOT installed (FA2 disabled; late chunking 8K peak ~4.3GB — see design §9)"
    except Exception:  # noqa: BLE001
        fa_status = "NOT installed (FA2 disabled; late chunking 8K peak ~4.3GB — see design §9)"

    print(
        {
            "model": args.model,
            "saved_to": str(output),
            "hybrid_heads": "ready",
            "flash_attn": fa_status,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
