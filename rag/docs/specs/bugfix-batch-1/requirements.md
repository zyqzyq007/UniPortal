# 需求文档：bugfix-batch-1

> 对抗式审查（批评者/辩护者）发现的 25 个问题，统一修复批次。
> 本文档只写「要解决什么、为什么、验收标准」；具体方案见 `design.md`。

## 1. 背景

对整个代码库做了一次批评者/辩护者对抗式评审，产出 25 个 findings，覆盖正确性、并发、安全、
架构、依赖、测试基建。这些是真实存在、会在生产中触发的问题（非风格问题）。本批次目标是
**一次性修复全部 25 项**，并同步把测试基建补齐到「全套含 Playwright + 真实后端进 CI」的标准。

## 2. 本质需求

- **正确性**：检索/状态/编排路径在并发与运行时变更下必须一致、可预测。
- **安全**：admin、SSRF、注入、PII 的加固必须在中文 PHM 真实场景下成立，而不是只防英文 demo。
- **可维护**：消除双布局/shim/私有调用等让 Agent（人或 AI）困惑的陷阱。
- **可测**：CI 绿要能代表「飞轮真能检测幻觉」「检索真能读到新文档」「前端真能用」。
- **可部署**：依赖体积、版本约束、大文件治理要适合气隙最小部署。

## 3. 范围（25 项，按工作包分组）

### WP1 正确性
- **F01** BM25 双实例分歧：`hybrid_retriever` 新建实例 vs documents 路由用单例 → 上传/删除后 BM25 不更新。
- **F02** grade 作为条件边无法持久化 before-hook `shared_state`（需守卫或转普通节点）。
- **F03** `merge_shared_state` 浅合并整键覆盖的契约需显式化（防误用）。
- **F04** `agent/context/state.py` 重复 `from utils.log_utils import log`。

### WP2 安全
- **F05** admin：缺启动校验（生产忘设 `ADMIN_API_KEY` 静默开放）+ key 用 `==`（时序）。
- **F06** SSRF：`_ssf_blocked`→`urlopen` 的 TOCTOU + 默认跟随重定向可被 302 引到内网/metadata。
- **F07** 注入模式缺中文（忽略以上指令/越狱/开发者模式等）。
- **F08** PII 缺航空场景（姓名/护照/机尾号/MSN/航线），且无法处理改写式 PII（接 opt-in LLM 通路）。
- **F09** calculator `eval()` → 改 `ast` 安全求值；修正 `abs`/`pow` 不可达。
- **F10** output guardrail：PII SANITIZE 的 `return` 覆盖 ESCALATE（幻觉答案含 PII 被脱敏后下发）。

### WP3 并发/性能
- **F11** 类级共享 `ThreadPoolExecutor(max_workers=2)` 成为全局检索瓶颈 → 改实例/`asyncio.to_thread`。
- **F12** 同步 `invoke()` 在多 worker 下 sqlite 共享连接非线程安全 → 守卫或文档化强制 async。
- **F13** 检索缓存 `deepcopy` 每次 miss 开销未基准（已修复正确性，需量化并优化）。
- **F14** 单例 harness trace 隔离依赖 contextvar 传播，无并发测试守卫。

### WP4 架构/可维护
- **F15** 技能双布局 + shim 文件 + `agent/skills/README.md` 过时 → 删 shim、更新 README。
- **F16** 无 app factory，e2e 须 monkeypatch 源模块 → 引入 `create_app()` + `Depends` 注入。
- **F17** `grounding_guardrail` 调 judge 私有 `_entail`/`_aentail` → 暴露公开契约。
- **F18** `_get_doc_id` 仅 hash 前 500 字符 → 共享前缀文档在 RRF 被合并丢弃。
- **F19** 检索 sync/async ~90% 重复，缓存写需手工双处同步 → 抽公共方法。

### WP5 依赖/发布
- **F20** `paddlepaddle`/`paddleocr` 硬依赖 → 改可选 `[ocr]` extra。
- **F21** langchain/langgraph 无版本上限，依赖 contextvar 传播 → 加兼容版本上限 + 测试守卫。
- **F22** 仓库追踪 `bge.../model.safetensors`（95MB）→ 迁 LFS 或发布产物。
- **F23** 无 CHANGELOG/semver，stage 分支与 main 分歧 → 建立 CHANGELOG 与版本纪律。

### WP6 测试基建
- **F24** `tests/api/`、`tests/integration/` 不在 CI；飞轮 E2E 用 fake judge。
- **F25** 无 Playwright 前端 E2E。

## 4. 不做（显式排除）

- 不更换检索/LLM/向量库技术栈。
- 不引入新的外部依赖（PII LLM 通路用现有本地 Qwen3）。
- 不重构前端框架（仅加 Playwright 测试）。
- 不做多副本部署的分布式存储改造（SQLite 在单节点气隙场景是正确选择）。

## 5. 验收标准（每项都必须有对应测试）

通用：
- AC-G1 `python -m pytest tests/unit/ tests/e2e/ -q` 全绿，且新增的每个修复都有对应断言。
- AC-G2 Playwright `tests/e2e_ui/` 覆盖 chat/SSE/文档上传/会话/反馈并通过。
- AC-G3 `tests/integration/` 与真实 judge 飞轮 E2E 进入 CI（带 service 标记，可选触发）。
- AC-G4 `python -c "import api.main"` 无回归。

逐项关键验收：
- AC-F01：测试「documents 上传 → 混合检索读出 BM25 命中新文档」一致。
- AC-F05：未设 `ADMIN_API_KEY` 且非 loopback 时启动即报错；key 比较用常量时间。
- AC-F06：`http_get` 不跟随到内网/metadata；TOCTOU 用解析时锁 IP 缓解。
- AC-F07：中文注入样本（"忽略以上指令""你现在是DAN""越狱"）被 BLOCK。
- AC-F10：含 PII 的幻觉答案同时被脱敏**且**保留 ESCALATE 元数据（不下发为干净答案）。
- AC-F15：`agent/skills/*_skill.py` 删除后 `import api.main` 与全测试通过。
- AC-F16：新路由不再需要改 conftest 的 monkeypatch 列表即可被 e2e 测试。
- AC-F20：`uv sync`（无 extras）不安装 paddlepaddle；`uv sync --extra ocr` 可用 OCR。
- AC-F25：`npx playwright test tests/e2e_ui/` 绿，CI 有独立 job。

## 6. 非功能要求

- **降级**：所有新增/改动热路径遵守「不可用 ≠ 0 分」与既定降级矩阵（AGENTS.md §8）。
- **离线**：修复后 `deploy.sh --build-offline-bundle` 仍可生成可用离线包。
- **回滚**：每个 WP 独立可回滚（独立 commit/PR），互不阻塞。
- **性能**：F13 给出 deepcopy 前后基准；F11 给出检索吞吐前后基准。
