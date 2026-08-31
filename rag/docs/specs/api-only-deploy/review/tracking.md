# Tracking — api-only-deploy

> 闭环追踪矩阵。按 `docs/specs/prompts/tracking.md` 模板。Critical/High 必须 4 列全填才能 `closed`
> （发现 → 修复 commit / 验证测试 / 回归测试 / 状态）。Medium/Low 须 closed 或 accepted-with-rationale。

**评审轮次**：v1（critic + defender 并行）→ v2 修订。
**合并门禁**：所有 Critical 必须 `closed`；High 必须 `closed` 或 `defended-with-alternative`。

## F-编号 → REQ → 修复 → 测试 → 状态（四列）

### Critical（必须 4 列全填才能 closed）

| id | finding | REQ | 修复（commit/design） | 验证测试 | 回归测试（固化） | 状态 |
|----|---------|-----|----------------------|----------|------------------|------|
| F-01 | 维度漂移：collection 先于 adapter 校验建表 | REQ-AO-005 | design v2 §2.1 `_echo_check`（响应真实维度回声校验）+ §2.2 adapter init 校验 | `tests/unit/test_dashscope_embeddings.py::test_dimension_echo_check`（mock 返回 1024 但 dim=512 → raise） | `test_search_cold_path_dim_mismatch_raises`（固化回声校验覆盖 search 冷路径） | **closed**（v2 §2.1/§2.2 + 测试） |
| F-02 | auto 默认 + 空 key 静默失败 | REQ-AO-001 | design v2 §2.2 `_get_api_embeddings` 空 key raise 清晰错误 | `tests/unit/test_embedding_provider.py::test_auto_falls_back_to_api_raises_on_empty_key` | `test_explicit_local_missing_torch_raises_clear_message`（固化本地迁移指引） | **closed**（v2 §2.2 + 测试） |

### High（必须 closed 或 defended-with-alternative）

| id | finding | REQ | 修复 | 验证测试 | 回归测试 | 状态 |
|----|---------|-----|------|----------|----------|------|
| F-03 | 非 v3 模型发 `dimension` 报错 + 缺 output_type | REQ-AO-005 | design v2 §2.1 model-family 分支（非 v3 省略 dimension）+ 显式 `output_type=dense` | `test_v1_model_omits_dimension`（golden payload 不含 dimension）+ `test_explicit_output_type_dense` | golden snapshot（v3 + 非 v3 两份）固化 | **closed**（v2 §2.1 + golden） |
| F-04 | eval 并发阻塞事件循环 | —（容量） | **不处理（backlog）** | — | — | **defended-with-alternative / accepted-no-regression**（PM-02 证明 hybrid_retriever 已 `run_in_executor`；eval 路径变更前即同步，非回归；登记 §12 backlog） |
| F-05 | 单例 provider 缓存 + 测试密封性 | REQ-AO-012 | design v2 §2.2 `_resolve_provider` 改读 live `os.getenv` | `test_provider_switch_after_reset`（setenv + reset 生效）+ `test_setenv_does_not_leak_singleton` | `test_embedding_provider.py` 单例隔离固化 | **closed**（v2 §2.2 + 测试） |
| F-06 | `_detect_device` 短路不可达 | REQ-AO-001 | design v2 §2.3 定位修正：短路为 clear-only；REQ-AO-001 闭合靠 dep 重构（Stage 3）+ lazy import（Stage 1） | `test_env_utils_import_without_torch`（stub torch，import 不 raise） | CI `uv sync --frozen --no-dev --extra api-only` 后 `python -c "import torch"` ImportError | **closed**（v2 §2.3 定位 + Stage 1/3 闭合） |
| F-07 | SSRF / credential-leak 不对称 | REQ-AO（安全） | design v2 §2.1 `_validate_base_url` scheme 校验 + §9 登记 `OPENAI_BASE_URL` debt；可选 `DASHSCOPE_ALLOWED_HOSTS` | `test_base_url_scheme_validation`（非 http(s) raise）+ `test_allowed_hosts_whitelist` | scheme 校验固化 | **closed-with-hardening**（operator-trust 保留 PM-05，加最小 scheme 校验） |

### Medium

| id | finding | REQ | 修复 | 验证测试 | 状态 |
|----|---------|-----|------|----------|------|
| F-08 | 降级表语义分层不清 | §0.3/§0.5 | design v2 §6 分层（adapter raise / retriever 空候选 / 写路径 5xx） | `tests/e2e/`：query 失败返回空列表（非 0 分）；写失败 5xx | **closed**（v2 §6） |
| F-10 | `--frozen` + 空 extra 验证缺失 | REQ-AO-002 | tasks Stage 4 增验证步骤 | CI `docker-api-only.yml` step「assert no torch」 | **closed**（tasks Stage 4） |
| F-12 | PII 出站评估缺失 | §8 PII | design v2 §9 增「PII 出站评估」段 + `.env.example` 注释 | 文档审查（无代码测试） | **accepted-with-known-limitation**（摄入脱敏另立 spec，§12 backlog） |

### Low

| id | finding | REQ | 修复 | 状态 |
|----|---------|-----|------|------|
| F-11 | `.env.example` 未显式 `EMBEDDING_PROVIDER` | REQ-AO-013 | tasks Stage 5：本地段加 `EMBEDDING_PROVIDER=local`；API-only 段加 `EMBEDDING_PROVIDER=api` | **closed**（tasks Stage 5） |

### Pre-mortem PM 编号（defender 独立产出，与 F 编号协调）

| PM | 决策 | 对应 F | 状态 |
|----|------|--------|------|
| PM-01 | concede-needs-revision | F-02 | closed（见 F-02） |
| PM-02 | defended | F-04/F-09 | accepted-no-regression |
| PM-03 | concede-needs-revision | F-01 | closed（见 F-01） |
| PM-04 | concede-needs-revision | F-03 | closed（见 F-03） |
| PM-05 | defended（+hardening） | F-07 | closed-with-hardening（见 F-07） |
| PM-06 | defended（+testability 强化） | F-05 | closed（见 F-05） |
| PM-07 | defended-with-alternative | —（lazy import 顺序） | closed（design v2 §3 + tasks Stage1→3 顺序） |
| PM-08 | defended | —（别名） | closed（调用点改名可选，别名保留） |

## 闭环小结

- **Critical（2/2）**：F-01、F-02 全部 closed。
- **High（5/5）**：F-03/F-05/F-06/F-07 closed；F-04 defended-with-alternative（accepted-no-regression + backlog）。
- **Medium（3/3）**：F-08/F-10 closed；F-12 accepted-with-known-limitation（backlog）。
- **Low（1/1）**：F-11 closed。

**门禁达成**：可进入编码阶段。编码须按 tasks.md Stage 1→2→3→4→5→6 顺序（PM-07 强依赖）。
