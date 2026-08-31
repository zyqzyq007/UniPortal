# Reranker 默认开启 + 设备智能探测 — 任务清单

> 每条任务回指 `requirements.md` 的 `REQ-RD-xxx`。

## 核心代码

- [ ] T1 [REQ-RD-004/005]: `utils/env_utils.py` 新增 `_detect_device()`（镜像
      `tests/e2e/test_e2e_coverage.py:_gpu_kernel_supported` 的 sm_xx arch 检查）+ `_resolve_device()`。
- [ ] T2 [REQ-RD-004]: `utils/env_utils.py:56` `EMBEDDING_DEVICE` 默认 `"cpu"` →
      `_resolve_device("EMBEDDING_DEVICE", "auto")`。
- [ ] T3 [REQ-RD-001]: `utils/env_utils.py:61` `RERANKER_ENABLED` 默认 `False` → `True`。
- [ ] T4 [REQ-RD-002]: `utils/env_utils.py:62` `RERANKER_MODEL` 默认 → `"BAAI/bge-reranker-v2-m3"`。
- [ ] T5 [REQ-RD-003]: `utils/env_utils.py:63` `RERANKER_MODEL_PATH` 默认 `""` →
      `"models/local_models/reranker/bge-reranker-v2-m3"`。
- [ ] T6 [REQ-RD-004]: `utils/env_utils.py:64` `RERANKER_DEVICE` 默认 `"cpu"` →
      `_resolve_device("RERANKER_DEVICE", "auto")`。

## 部署配置同步（防漂移）

- [ ] T7 [REQ-RD-006]: `.env.example` L29/L35/L38 → `EMBEDDING_DEVICE=auto`、
      `RERANKER_ENABLED=true`、`RERANKER_DEVICE=auto`。
- [ ] T8 [REQ-RD-006]: `deploy.sh` Block1（写盘模板）L313/L318/L321 同上。
- [ ] T9 [REQ-RD-006]: `deploy.sh` **Block2（offline `:-` fallback，最危险）** L505/L519/L523/
      L524/L525/L526：模型名→bge、path 跟随、enabled→true、device→auto。

## 文档同步

- [ ] T10 [REQ-RD-006]: `README.md` env 表（L326/L330-333）+ quickstart（L105）+
      reranker 启用块（L412-419，改「默认已启用」）+ 措辞（L423/L439/L443）。
- [ ] T11 [REQ-RD-006]: `docs/API.md` `/api/admin/config` 示例 L1165-1173。
- [ ] T12 [REQ-RD-006]: `docs/technical_report.md` L572「默认 MiniLM」表述。

## 测试（红→绿 + 密封性）

- [ ] T13 [REQ-RD-008]: `tests/unit/test_model_config.py` 加 `test_reranker_defaults_on`
      （断言 enabled True / model bge / path 非空含 bge）。先红后绿。
- [ ] T14 [REQ-RD-008]: `tests/unit/test_model_config.py` 加 `test_auto_device_resolves`
      （mock torch.cuda：可用+arch 命中→cuda；arch 不命中→cpu；torch 缺失→cpu）。先红后绿。
- [ ] T15 [REQ-RD-007]: `tests/conftest.py:506` 旁加 `monkeypatch.setattr("utils.env_utils.RERANKER_ENABLED", False)`，
      保进程内 E2E 确定性。
- [ ] T16 [REQ-RD-006]: 审计 `tests/api/test_admin*.py`、`tests/e2e/test_e2e_coverage.py`，
      确认无断言 reranker absent/disabled 被翻转打穿（若有则修）。

## 变更记录 + 验证

- [ ] T17 [REQ-RD-006]: `CHANGELOG.md` `[Unreleased]` 加 `[breaking]` 条目
      （改了什么/为什么/如何迁移）。
- [ ] T18: 验证矩阵：`import api.main` + `pytest tests/unit tests/e2e`（落盘
      `/tmp/reranker_default.log`）+ GPU 冒烟（`Reranker(device=cuda).load()` → `degraded=False`）。

## 不在范围（明确边界）

- 不动 `RERANKER_BATCH_SIZE`（代码 8 / `.env.example` 4 的预存漂移，未要求）。
- 不动 gitignored 本地 `.env`（已配好 cuda+bge）。
- 不删 `ms-marco-MiniLM-L-6-v2/` 模型目录（保留为可切换选项）。
- 不改 `docs/specs/retrieval-stack-bm25-reranker/*`（历史迁移叙事，CONTEXTUAL）。

## 评审门禁（§1.3）

- [ ] T19: 本次为配置默认值翻转（非热路径逻辑、非新功能架构），风险面经全面探测已穷尽。
      spec 已归档。若 maintainer 要求严格对抗式评审，补跑 critic+defender 子 Agent 并行评审。
