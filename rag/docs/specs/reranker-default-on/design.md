# Reranker 默认开启 + 设备智能探测 — 设计

## 1. 架构概览

本次改动是**配置默认值翻转 + 设备探测逻辑**，不引入新模块、不改 Graph 拓扑、不改热路径控制流。
唯一新增逻辑在 `utils/env_utils.py`（设备探测），其余文件为默认值/文档/部署模板同步。

```
                    ┌──────────────────────────────────────────┐
  环境变量 / .env ──▶│ utils/env_utils.py (唯一改逻辑的源文件)    │
                    │  _detect_device() ── cuda 可用+sm_xx 命中?  │
                    │     ├─ 是 → "cuda"                          │
                    │     └─ 否 → "cpu" (永不抛, REQ-RD-005)       │
                    │  _resolve_device(name, default)             │
                    │     └─ value=="auto" → _detect_device()     │
                    │                                             │
                    │  导出永远是具体 device (cuda/cpu)            │
                    │  绝不导出 "auto" 字面量 (REQ-RD-004)         │
                    └────────────┬────────────────────────────────┘
                                 │ (cuda/cpu, 已解析)
            ┌────────────────────┼────────────────────┐
            ▼                    ▼                    ▼
  EMBEDDING_DEVICE      RERANKER_DEVICE       (其余 RERANKER_* 直读)
  → models/             → core/retrieval/     → 配置消费方零改动
    embedding_models      reranker.py           (device= 已是有效值)
    .py:47 device=        :119 device=
```

三个 device= 消费方（`models/embedding_models.py:47`、`core/retrieval/reranker.py:119`、
`scripts/download_reranker.py:36`）**零改动**——因为它们拿到的永远是已解析的具体 device。

## 2. 核心改动：`utils/env_utils.py`

### 2.1 新增探测函数（镜像既有测试逻辑）

```python
def _detect_device() -> str:
    """Resolve 'auto' to a concrete torch device. cuda only when the installed
    wheel actually ships a kernel for this GPU's compute capability — else a
    cu126 wheel on sm_120 (RTX 50-series) silently fails with
    cudaErrorNoKernelImageForDevice. Mirrors
    tests/e2e/test_e2e_coverage.py:_gpu_kernel_supported so probe + skip agree.
    """
    try:
        import torch

        if torch.cuda.is_available():
            cap = torch.cuda.get_device_capability(0)
            if f"sm_{cap[0]}{cap[1]}" in torch.cuda.get_arch_list():
                return "cuda"
    except Exception:  # noqa: BLE001 — probe MUST degrade silently (REQ-RD-005)
        pass
    return "cpu"


def _resolve_device(name: str, default: str) -> str:
    """Read a device env var; resolve 'auto' to cuda/cpu."""
    value = os.getenv(name, default)
    if value.strip().lower() == "auto":
        return _detect_device()
    return value
```

**为何镜像 `_gpu_kernel_supported`**：该测试 helper 已确立「cuda 可用 + arch_list 命中 sm_xx 才算
真正支持」的项目约定（AGENTS.md §5 torch wheel arch 约束）。探测函数与 skip 逻辑用同一判定，
保证「部署时探测用 GPU」与「测试时判定 GPU 可跑」永远一致，杜绝「探测说 cuda、测试却 skip」的割裂。

### 2.2 五个默认值翻转（L56 / L61-64）

| 行 | 变量 | 旧默认 | 新默认 |
|----|------|--------|--------|
| L56 | `EMBEDDING_DEVICE` | `"cpu"` | `_resolve_device("EMBEDDING_DEVICE", "auto")` |
| L61 | `RERANKER_ENABLED` | `False` | `True` |
| L62 | `RERANKER_MODEL` | `"cross-encoder/ms-marco-MiniLM-L-6-v2"` | `"BAAI/bge-reranker-v2-m3"` |
| L63 | `RERANKER_MODEL_PATH` | `""` | `_get_path("RERANKER_MODEL_PATH", "models/local_models/reranker/bge-reranker-v2-m3")` |
| L64 | `RERANKER_DEVICE` | `"cpu"` | `_resolve_device("RERANKER_DEVICE", "auto")` |

注：`_get_path`（L33-40）对相对路径返回**绝对解析路径**。新 `RERANKER_MODEL_PATH` 默认值经
解析后是绝对路径——`reranker.py:80` 的 `__post_init__` 相等性比较不受影响（比较的是
`RERANKER_MODEL_PATH` 模块常量本身，二者同源）。

## 3. 数据流与状态契约

### 3.1 `RerankerConfig` 默认值链
`core/retrieval/reranker.py:73-77` 的 `RerankerConfig` 字段默认值直接读 `env_utils` 常量：
`model_name=RERANKER_MODEL`、`model_path=RERANKER_MODEL_PATH`、`device=RERANKER_DEVICE`。
翻转后 `get_reranker()` 单例默认配置自动指向 bge + 本地路径 + 已解析 device——**reranker.py 零改动**。

### 3.2 `HybridRetrieverConfig` 默认值链（breaking，REQ-RD 风险点）
`core/retrieval/hybrid_retriever.py:44-57` 的类级默认值在**导入时**求值：
```python
dense_top_k: int = RERANKER_CANDIDATE_TOP_K if RERANKER_ENABLED else 5   # 5 → 10
sparse_top_k: int = RERANKER_CANDIDATE_TOP_K if RERANKER_ENABLED else 5  # 5 → 10
final_top_k: int = RERANKER_TOP_K if RERANKER_ENABLED else 5             # 5 → 5 (不变, TOP_K=5)
enable_reranker: bool = RERANKER_ENABLED                                  # False → True
```
无参 `HybridRetrieverConfig()` 语义从「reranker 关、候选池 5」变为「reranker 开、候选池 10」。
这是**预期且正确**的语义迁移（reranker 默认开后需更大候选池供精排筛选），但需审计所有无参构造点。

### 3.3 `shared_state` 影响
**无**。reranker/device 不写入 `shared_state`，无跨节点数据流。

## 4. 降级矩阵（AGENTS.md §0.5）

| 故障 | 触发 | 降级动作 | 上报 |
|------|------|----------|------|
| GPU 不可用 / wheel 缺 sm_xx kernel | `_detect_device` | 静默返回 `cpu`，绝不抛 | 无（探测层） |
| 设备探测异常（torch 导入失败等） | `_detect_device` 的 `except` | 静默返回 `cpu` | 无 |
| reranker 模型加载失败 | `Reranker.load` 的 `except` | `_load_attempted=True` 粘住，`rerank()` 回 RRF 顺序 | `/api/admin/health` `degraded=True` |
| rerank predict 失败 | `Reranker.rerank` 的 `except` | `_fallback_documents`（标记 `rerank_applied=False`） | doc metadata `rerank_error` |

关键不变量：**「不可用」绝不报告为「0 分」**。reranker 不可用时回退到上游 RRF 排序（上游 score 保留），
`None` 永不被当 0（AGENTS.md §0.3）。

## 5. 测试矩阵（AGENTS.md §1.1）

| 层 | 测试 | 红绿 |
|----|------|------|
| 单元（新） | `test_model_config.py::test_reranker_defaults_on`：断言 `RERANKER_ENABLED is True`、`RERANKER_MODEL == "BAAI/bge-reranker-v2-m3"`、`RERANKER_MODEL_PATH` 非空含 bge | 翻转前红、后绿 |
| 单元（新） | `test_model_config.py::test_auto_device_resolves`：mock `torch.cuda` 可用+arch 命中→cuda；arch 不命中→cpu；torch 缺失→cpu | 翻转前红、后绿 |
| 单元（既有） | `test_retrieval_optimization.py`（显式传 `enable_reranker=`） | 不变 |
| 进程内 E2E | conftest `client` fixture 加 `RERANKER_ENABLED=False` override | 确定性，不真加载模型 |
| admin/health | 审计 `tests/api/test_admin*.py`、`tests/e2e/test_e2e_coverage.py`：无断言 reranker absent/disabled | 不被翻转打穿 |
| GPU 冒烟（手动） | `Reranker(device=cuda).load()` → `degraded=False` | 已验证通过 |

## 6. 回滚

纯 env 覆盖即可回滚，无需改回代码：
```bash
RERANKER_ENABLED=false
# 若还想去 GPU：EMBEDDING_DEVICE=cpu RERANKER_DEVICE=cpu
```

## 7. 不变量影响

- **降级矩阵不变量**：增强（新增 `_detect_device` 的静默降级路径，与既有 reranker 降级互补）。
- **持久化契约不变量**：无新增持久化（reranker/device 无落盘），无模块级路径属性新增需求。
- **Prompt 单一来源**：无关。
- **shared_state 键所有权**：无关。

## 8. 安全影响

无新增攻击面。设备探测不读取外部输入、不联网（torch.cuda 查询为本地 GPU 能力查询）。
reranker 模型从本地路径加载（REQ-RD-003），不触发联网下载（气隙自洽，也避免供应链风险）。

## 9. 部署同步清单（REQ-RD-006）

| 文件 | 改动 |
|------|------|
| `.env.example` L29/L35/L38 | `EMBEDDING_DEVICE=auto`、`RERANKER_ENABLED=true`、`RERANKER_DEVICE=auto` |
| `deploy.sh` Block1（写盘模板）L313/L318/L321 | 同上 |
| `deploy.sh` Block2（offline `:-` fallback）L505/L519/L523/L524/L525/L526 | 模型名→bge、path 跟随、enabled→true、device→auto。**最危险**：不同步则气隙部署静默回退旧默认 |
| `README.md` env 表/quickstart | L105/L326/L330-333/L412-419/L423/L439/L443 |
| `docs/API.md` admin/config 示例 | L1165-1173 |
| `docs/technical_report.md` | L572「默认 MiniLM」表述 |

**不改动**（CONTEXTUAL）：`docs/specs/retrieval-stack-bm25-reranker/*`（历史迁移叙事）、
`CHANGELOG.md` 既有条目、`models/local_models/reranker/ms-marco-*/README.md`（模型卡）。
