# 辩护者报告：bugfix-batch-1 设计评审

> 评审对象：`docs/specs/bugfix-batch-1/{requirements,design}.md`
> 立场：论证方案合理、取舍正确、复用既有机制、诚实承认边界。

## 结论：**方案整体可辩护**。

经逐项对照代码验证，设计在几乎所有情况下选择了正确取舍，在风险与收益不匹配处选择保守，并忠实保留了既有不变量。每 WP 防御 + 必须保留的不变量清单 + 让步如下。

---

## 跨 WP：必须保留的不变量清单（实现者核对表）

| # | 不变量（来源） | 方案如何尊重 |
|---|---|---|
| I1 | 跨节点数据只走 `shared_state`；浅合并、整键覆盖（§4/§4.1） | F03 用回归测试**强化**而非改语义；F02 守卫防 grade 静默违反 |
| I2 | before-hook 增量在技能自身写**之下**合并（§4 row 2） | F02/F03 不动 `_merge_state_update` |
| I3 | 优雅降级：热路径 log+降级、永不抛；"不可用 ≠ 0 分"（§8） | F08/F13/F01/F06 全部显式降级；F10 修复的是对该不变量的**违反** |
| I4 | judge：本地、temp=0、缓存键 `(prompt_hash, model)`、None 永不当 0（§6/§8） | F08 复用 judge 熔断；F17 仅改名不改 temp |
| I5 | 单例 harness 每运行 trace 隔离 via contextvar（orchestrator `_run_trace_ctx`） | F14 加守卫测试；不动 `_begin_run`/`_end_run` |
| I6 | CORS 由 `ALLOWED_ORIGINS`；admin 生产必设 key（§9） | F05 加固而非削弱 I6 |
| I7 | SSRF：解析+拒私网；可选白名单；工具默认关（§9） | F06 强化解析路径，保留默认关与白名单 |
| I8 | 技能无状态；拓扑 `START→agent→[tools]→retrieve→grade→[gen\|rewrite]` | F02 拒绝改拓扑；F15 仅删 re-export shim |
| I9 | 混合检索失败降级 dense-only（§8 row 1） | F01/F11/F18/F19 全保留 try/except fall-through |
| I10 | BM25/混合改动须有"写入→读出"一致性测试（§7.2） | F01 正好出货该测试；AC-F01 编码之 |

---

## WP1 正确性

### F01 — 单例统一是正确且最小的
验证 BUG 真实：`hybrid_retriever.py:128-129` 新建 `BM25Retriever()`；`documents.py:355-357`/`:423-426` 调 `get_bm25_retriever()` 单例（`bm25_retriever.py:264-269`）。两个不相关对象 → 上传/删除永不到达检索器的 BM25。这是真 BUG。

为何选择的修复是对的取舍：
- **匹配既有写路径**。documents 已写单例；让读路径消费同单例是最小对称改动。"每次变更从 Milvus 重建"会丢弃已有 `add_documents`/`remove_by_source` 增量 API——纯浪费。
- **保留 I9**。降级故事不动：属性与 `_ensure_sparse_indexed` 仍包 try/except，单例不可用仍降 dense-only。
- **事件总线是错选择**。系统是单进程气隙（requirements §4 排除分布式存储），加事件总线违反"不引入新机制"非目标。
- 回滚注记诚实：还原属性即重开 BUG，但机械上可回滚。

> **接受批评者 C1**：但须按 C1 修订——弃"标记已建索引"捷径 + 加缓存失效 + 预热缓存测试。修订后方案仍属本辩护范围（单例统一的核心论点不变）。

### F02 — 保守的 log-only 守卫是正确取舍
验证 `orchestrator.py:430-497` 为条件边，line 446-451 已注释说明。转普通节点改拓扑，触及 I8、checkpointing、grade 路由契约、所有断言 node 集合的测试。BUG 是**潜伏的**（无钩子目标 grade）——不值得该爆炸半径。守卫把静默 footgun 变大声。

> **接受批评者 H1**：守卫必须覆盖两条丢失通道（before-hook 增量 **与** 技能自身 state_updates），放进 `_skill_to_conditional` 自身。

### F03 — 不改语义，冻结语义
浅合并整键覆盖是所有现有 producer/consumer 的承重契约（§4.1 显式记录）。改深合并会静默改变 `retrieved_contexts`/`sources`/`relevant_memories` 行为。冻结语义 + 回归测试是唯一安全选项。教科书式"契约漂移前先钉住"。

### F04 — 琐碎，但 F23 ruff/pre-commit 才是耐久修复
删重复 import 修实例；ruff 重复 import 规则防类。F04 单独是装饰，F04+F23 是结构性的。

---

## WP2 安全

### F05 — lifespan fail-fast + test carve-out 是对的
验证缺口：`api/main.py:28-66` 不校验 admin key；`admin.py:39-68` key 未设时对 loopback/testclient 开放。生产非 loopback 绑定下"忘设 key"=静默开放 admin。fail-fast 是标准解。

carve-out 是对的，不是弱点：条件合取——只在 (key 未设) **且** (ALLOWED_ORIGINS 仍本地默认) **且** (非 testclient/test_mode) 时触发，精确命中开放面。`hmac.compare_digest` 一行零成本防时序。

> **接受批评者 H2/H3**：但须按其修订——改抛 RuntimeError（防 restart-loop）、test-skip 用 `PYTEST_RUN` env（conftest 顶层设置）、比较不在 strip 后做（防长度泄露）。

### F06 — 解析时锁 IP + 控制重定向：正确的纵深防御
验证两缺陷：`tools_registry.py:241-254` 解析但 `http_get`（line 262-267）之后才 `urlopen`（TOCTOU），且 `urlopen` 默认跟随重定向（302→metadata 绕过）。

> **接受批评者 H5**：IP+Host 破坏 HTTPS SNI/证书。修订为：**禁用重定向**（HTTPRedirectHandler raise）+ 连接后 socket 级校验 peer IP ∈ 已校验集合；HTTPS 用 httpx 显式 `server_hostname`。复用 `_ssf_blocked`（I7）不变。默认关不变（line 93）。

### F07 — 中文注入模式，带精度
纯补缺（`INJECTION_PATTERNS` 全英文，requirements §2"中文 PHM 真实场景"）。AC-F07 要求**正常** PHM 问题（含"模式/规则"字样但不操控）不被误杀——负面测试使其可辩护。

### F08 — LLM-PII 复用 judge 熔断是模范复用
最强复用论据。`judge.py:209-239` 定义 `_FailureTracker`，`LLMJudge.available`（335-337）返回 `not self._failures.tripped`。grounding 守卫已依赖此模式（`grounding_guardrail.py:104-108`）。PII LLM pass 复用同一 judge 单例熔断 → 全进程单一降级机制（I3/I4 保留）；"LLM 不可用 → 仅正则"匹配"不可用 ≠ 0"。高误报检测器（百家姓、航班号）默认关 + env + 文档警示——保守且对。

> **接受批评者 H6**：机尾/MSN 重分类为非 PII 或独立 flag；LLM-PII span 禁遥测；测试断言 PII-judge 不被 sampler 捕获。

### F09 — `ast` 优于 `eval` 无争议
验证 `tools_registry.py:124-148`：剥离函数名（字符串 replace，非 parse）+ 字符白名单 + `eval`；`abs`/`pow` 在 namespace 但不在剥离列表 → 因字符白名单不可达。`ast.parse`+NodeVisitor 白名单是教科书修复，且**恢复** `abs`/`pow`。无取舍，方案就是对的。

### F10 — 复合结果保留文档化优先级
验证 BUG `output_guardrails.py:223-242`：PII 分支无条件 `return` SANITIZE，丢弃 `worst`（ESCALATE）。头部注释 line 200 文档"BLOCK>ESCALATE>SANITIZE>ALLOW"——代码违反自己的文档。修复（合并 sanitized_content 进 worst，保 ESCALATE 动作，附 PII 元数据）是唯一与文档化优先级一致的修复，与 I3 一致。

> **接受批评者 C2**：但须补消费侧——`manager.py:142-149` ESCALATE 分支须应用 `sanitized_content`；AC 断言**实际下发** message 已脱敏。

---

## WP3 并发/性能

### F11 — 实例 executor + asyncio.to_thread
验证 `hybrid_retriever.py:450` 为类属性，全局 2-worker 池。异步路径已在 `run_in_executor(None,...)`（363-369，默认无界池），设计**显式不动它并文档化**——正确判断（异步路径非瓶颈）。降级（I9）：`_dense_retrieve`/`_sparse_retrieve` 的 try/except 不动。

> **接受批评者 M1**：但核心是 `max_workers` 可配 + shutdown hook；须在 `api/main.py` lifespan shutdown 调 `get_hybrid_retriever().close()`。

### F12 — 守卫 sync，不删
验证 `orchestrator.py:545-557` sync `_setup_checkpointing` 开 `check_same_thread=False` 无锁。设计**加锁而非删 sync**——CLI/脚本依赖 sync（设计已说），删 sync 破非服务调用者。

> **接受批评者 H4**：连接层锁无效。修订为 `invoke()`/`stream()` 边界锁，或 sync 路径在非主线程 raise。

### F13 — 先基准再优化
设计"先量、超阈值才优化、否则保 deepcopy"是科学诚实位。deepcopy 是**正确性修复**（防缓存突变泄漏，注释 hybrid_retriever.py:220-223），盲删会回归正确性。

> **接受批评者 M5**：弃 `pytest-benchmark`（新依赖违反 requirements §4），改 `time.perf_counter` + 硬阈值。

### F14 — contextvar trace 隔离守卫测试
验证机制（`orchestrator.py:44-46`/520-543）。设计补的是 §7.2 显式要求的并发测试。非 BUG 修复，是关闭测试债、保护 I5。可辩护且必要。

---

## WP4 架构/可维护

### F15 — 删 shim，纯消除混淆
验证 6 shim 为一行 re-export；harness 已从真位置导入（`orchestrator.py:182-187`）。删除 + README + 负向测试是干净解。AC-F15（删后 `import api.main` 绿）是正确回归门。

> **接受批评者 M2**：F15 PR 含对 `docs/**/*.md` 与根 markdown 的 grep，更新 README 与文档代码块。

### F16 — 两步 app-factory 迁移是风险可控的正确取舍
最大改动，设计**拆分**处理是对的：step1 引 `create_app`+`Depends`，step2 逐路由迁移各一 commit。一次性全改不可审不可滚。依赖箭头（F16 先，其后 WP 的 e2e 测试对 `dependency_overrides` 而非 monkeypatch）正因 F16 改测试接线基底。保留 uvicorn 入口（`api/main.py: app=create_app()`），AC-G4/部署不变。`Depends`+`dependency_overrides` 是 FastAPI 惯用注入机制，替代非惯用的"monkeypatch 源模块"hack——真改进。

> **接受批评者 M3**：两步拆分使 AC-F16 在 step1 不可达。修订为**单一原子 PR**：factory + 全端点迁移 + `instrument_fastapi`/CORS/静态 mount/SPA catch-all 全进 `create_app`。

### F17 — 暴露 entail/aentail，委托既有私有
验证 `grounding_guardrail.py:132`/`:205` 调私有。加公开方法委托——最小 API 面改动，不改行为/契约（I4）。纯清理零风险。

### F18 — hash 全文
验证 `hybrid_retriever.py:528-533` 仅 hash 前 500 字符。航空手册语料共享 500 字符头/样板很常见 → RRF 合并丢文档。全文 md5 O(content) 可忽略；AC-F18 精确。

> **接受批评者 M6**：部署时 bump cache-version / lifespan 清一次缓存。

### F19 — 抽 `_retrieve_pipeline`，不重写双路径
验证重复（retrieve 161-242 vs aretrieve 244-325，含双处缓存写 deepcopy 224-231/311-319）。抽纯逻辑 + async 经 `asyncio.to_thread` 调——消双维护（F13/deepcopy 那类 bug 曾须双处补）。正确保留 `asyncio.to_thread` 语义。

---

## WP5 依赖/发布

### F20 — lazy import + `[ocr]` extra：保能力、缩最小安装
验证 `pyproject.toml:49-50` paddle 无条件依赖。paddle 是大框架；气隙最小部署可能不需每节点 OCR。三段取舍对：lazy import（`ocr_engine.py:54` 已部分做）保 `import api.main` 无 paddle；`[ocr]` extra 一命令可选；**`deploy.sh` 默认装 ocr extra** 保离线包不失 OCR（关键细节，否则"能力保留"是谎）。

### F21 — 版本上限 + contextvar 守卫
加 `langgraph<2.0.0` 等是标准 pin 纪律（trace 隔离 I5 依赖 langgraph contextvar 行为）。F14 并发测试即升级守卫。合理低风险。

### F22 — 新文件 LFS，不重写历史
默认"LFS 仅新文件、不 migrate 历史"是正确保守取舍。`git lfs migrate --everything` 重写所有 commit SHA，破坏每个外部 clone、下游分支、`sync-to-mirror.yml`、以及 inference 记录里的 `git_commit` 字段（`admin.py:429`）。设计正确标"需团队拍板"。95MB 已付一次性成本，前瞻修复（新模型文件→LFS）是耐久部分。

> **接受批评者 M7**：设计显式声明"默认路径不减现有 clone 体积，仅防未来；缩减需团队 migrate"。

### F23 — CHANGELOG + ruff + pre-commit + semver
纯流程卫生，使 F04 耐久。`pyproject.toml:7` 已 `version="0.1.0"`，从此 semver 一致。零风险。

---

## WP6 测试基建

### F24/F25 — 测试分层是务实且诚实的
最强辩护：设计**拒绝假装**。"全套含真实后端进 CI"的诱惑是把 Ollama+Milvus 塞每个 PR，使 PR 慢/抖/反气隙。设计：PR 跑 unit+e2e（fake judge，快/确定/无外部依赖，匹配 §7.1 既有 CI 契约）；nightly/self-hosted 跑 `requires_backend`/`requires_ollama`。这是把 `tests/api`/`tests/integration` 从"手跑"提升到"nightly-self-hosted"——严格改进。`@pytest.mark.requires_backend` 标记是表达"需真实服务"的诚实方式，不谎报 CI 覆盖。

> **接受批评者 P1**：编码 F24 前先验证 self-hosted runner 注册且有 GPU/Ollama；否则 F24 降级为"写好+标记，nightly 按 runner 可用性触发"，AC-G3 显式条件化。

### F25 — Playwright 最后
前端本批无结构改动，对稳定前端跑 Playwright 比跨 UI 变化维护便宜。`web/dist` build + 后端 + `npx playwright test` + 独立 CI job 是标准形态。

> **接受批评者 P2**：SSE 测试指定等待策略（JS 层 mock EventSource 求稳）；CI 独立 Node job；`web/playwright.config.ts` 新建。

---

## 让步（真实弱点，简述）

1. **F02 守卫是检测非修复**——若未来真需 grade 写状态，守卫只抱怨不解决。设计已承认，指向"转普通节点"。对潜伏 BUG 可接受，实现者勿把守卫当正确性。
2. **F03 冻结的语义本身令人意外**——整键覆盖对列表型键是 footgun。文档+测试缓解不消除。
3. **F08 姓名检测**即便默认关，对真实航空文本仍会误报；env-gating 对但须显著警示。
4. **F22 不 migrate 历史**留下 95MB 永久。设计诚实但须显式说明不减体积。
5. **F16 迁移期 inline getter** 是中间态 code smell——按 M3 修订为原子 PR 后此项消失。

无一条升至阻塞；每条都是已知、文档化、有命名逃生口的限制。

---

## 最终结论

**方案可辩护（经修订后）**。设计一致地：(a) 复用既有机制而非新造（F08 judge 熔断、F06 `_ssf_blocked`、F19 async executor）；(b) 在风险与收益不匹配处选保守（F02 log-only、F03 冻结语义、F22 不重写历史、F12 锁不删）；(c) 加固 §9 安全不变量而非削弱（F05/F06/F09/F10）；(d) 尊重 §4/§8 每条"必须保留"不变量——尤其 I3/I4/I5/I8。WP 拆分 + F16 先行的依赖排序是正确关键路径；F24/F25 测试分层是气隙系统下"真实后端进 CI"的诚实读法。

需在编码前纳入的修订（来自批评者，本辩护者接受）：
- C1（F01 缓存失效 + 弃捷径 + 预热测试）
- C2（F10 消费侧应用 sanitized_content + AC 断言下发 message）
- H1（F02 守卫覆盖两通道）
- H2/H3（F05 RuntimeError + PYTEST_RUN + 非 strip 比较）
- H4（F12 边界锁）
- H5（F06 禁重定向 + peer-IP 校验，弃 IP+Host）
- H6（F08 机尾/MSN 非人 PII + LLM-PII 禁遥测）
- M1/M3/M5/M6/M7（见对应条目）
- P1/P2/P3（runner 健康先验、Playwright CI 形态、testpaths/AC-G1）
