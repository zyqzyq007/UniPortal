# 批评者报告：bugfix-batch-1 设计评审

> 评审对象：`docs/specs/bugfix-batch-1/{requirements,design}.md`
> 方法：逐项对照代码（`file:line`）验证方案是否真正修复、是否引入新风险、测试计划是否充分。

## 结论：**需修订后再编码**。

存在 2 个 Critical（方案未真正闭合 BUG）与多个 High（错层/欠定义/新风险）。WP 边界与回滚计划是稳健的；F20/F15/F17/F09/F04/F18/F19 可基本照原方案推进。

---

## CRITICAL（必须编码前解决）

### C1 — F01 方案未闭合；"标记已建索引"会永久隐藏新文档
`core/retrieval/hybrid_retriever.py:126-159`、`core/retrieval/bm25_retriever.py`、`api/routers/documents.py`

设计说：hybrid 用单例 + "保留 `_ensure_sparse_indexed` ... 引导后标记已建索引避免重复全量加载"。三处自相矛盾/未闭合：

1. `_ensure_sparse_indexed` 当前 gate `if self._sparse_retriever._index_built and self._sparse_retriever._documents: return`。若单例从 Milvus 引导一次（`_index_built=True`），守卫会**永久短路**。后续上传若 `add_documents` 抛错被 `documents.py` 吞掉，单例即变陈旧且不再重新引导——设计里的"标记已建索引"正是回归路径。
2. **检索结果缓存无失效**（`hybrid_retriever.py:185-194` 命中即返回）。即便 BM25 修对，缓存键 `(query, filter, top_k)` 仍会服务上传前的旧答案。AC-F01 在冷进程过、在热进程挂——flaky。
3. 写路径**已**调单例 `add_documents`（`documents.py:357`），所以 BUG 仅在读路径（`hybrid_retriever.py:129` 直接 `BM25Retriever()`）。最小正确修复 = **一行属性改 `get_bm25_retriever()` + 上传/删除时失效缓存**，而非同时动两侧再加危险的引导守卫。

**改法**：(a) 属性返回 `get_bm25_retriever()`；(b) **删除**"标记已建索引避免重载"——引导仅在为空时重跑，永不假设新鲜；(c) 增缓存失效钩子（清 `get_retrieval_cache()` 或按 index-version 计数器命名空间，每次 `add_documents`/`remove_by_source` 自增）；(d) 测试必须在**预热缓存**下跑（先填缓存再上传）证明失效。

### C2 — F10 方案不完整：ESCALATE 消费者从不应用 `sanitized_content`
`agent/guardrails/output_guardrails.py:225-242`、`agent/guardrails/manager.py:142-149`

设计说 PII 分支"保留 ESCALATE + 附 `sanitized_content`"。但 ESCALATE 消费者 `create_after_hook`（`manager.py:142-149`）只写 `result.metadata["guardrail_escalation"]`，**从不读 `sanitized_content`**。即便 producer 正确返回 ESCALATE+脱敏，`last_msg.content`（含 PII 的幻觉答案）仍**原样下发**。F10 目标（PII 幻觉答案既脱敏又升级）落空。设计只写了 producer 侧。

**改法**：扩展 `_after_hook` 的 ESCALATE 分支，当 `sanitized_content` 存在时也写 `last_msg.content = sanitized_content`。补 AC：ESCALATE-with-PII 时下发的 message 含 `[已脱敏:...]` 而非原始 PII；测试必须断言**实际下发的 message**，不只断言 GuardrailResult 字段。

---

## HIGH

### H1 — F02 守卫错层：只拦 before-hook 增量，不拦 grade 技能自身的 state_updates
`agent/harness/orchestrator.py:430-497`

`_skill_to_conditional` 有**两条**丢失通道：(1) before_increments 计算后被丢弃（line 445）；(2) grade 技能自身 `result.to_state_update()` 永不应用，只用 `result.next_action`（line 464）。设计的守卫在 `LifecycleManager.fire_before_skill`，只覆盖通道 (1)。今天 grade 不写状态（`grade/skill.py` 仅返回 metadata），但守卫必须覆盖两条通道才算真守卫。

**改法**：守卫放进 `_skill_to_conditional` 自身，断言 `before_increments` 为空 **且** `result` 不带 `state_updates`/`shared_state`。

### H2 — F05 `sys.exit(1)` 在 lifespan + 欠定义的 test-mode 跳过 = 重启循环风险
`api/main.py:28-82`

1. `PYTEST_RUN`/`app.state.test_mode` 当前都不存在（grep 确认）。`app.state.test_mode` 不可靠——`TestClient(app)` 在用户 fixture 设置 `app.state` **之前**就进入 lifespan。`PYTEST_RUN` 必须在 `pyproject.toml [tool.pytest.ini_options]` 或 CI step 设置，设计未指明。
2. `sys.exit(1)` 在 `asynccontextmanager` lifespan 下，uvicorn worker/Docker `restart: always` 会**重启循环**一个配错的机器。

**改法**：(a) lifespan 抛清晰 `RuntimeError`，uvicorn 记一次日志后非零退出；deploy.sh 文档 `restart_policy.condition: on-failure` + max-attempts；(b) test-skip 用 `os.environ.get("PYTEST_RUN")=="1"`，在 `tests/conftest.py` 顶层设置；(c) AC-F05 同时断言"生产无 key 时非零退出"**与**"test-mode 不退出"。

### H3 — F05 `hmac.compare_digest` 配 `.strip()` 泄露长度
`api/routers/admin.py:39,48`

`compare_digest(a,b)` 在**长度不同时短路**，泄露配置 key 长度。对 configured key `.strip()` 本身可疑（有意外白空格的 key 被静默改写）。

**改法**：在 config-load 时校验 key 无首尾空白且长度合理；比较用 `compare_digest(x_admin_key.encode(), configured.encode())`，不在比较时 strip。文档说明定长 token 才不泄露。

### H4 — F12 锁错层；SqliteSaver 内部拥有写路径
`agent/harness/orchestrator.py:545-563`

`SqliteSaver(conn)` 接管连接，在 `SqliteSaver.put/get` 内部写（LangGraph 调用）。harness 侧无 hookable 的"写"方法可包。harness 持的锁 `SqliteSaver` 不会获取——什么都不串行化。

**改法**：选 (a) 在 `invoke()`/`stream()` 边界持全局锁包 `self.graph.invoke(...)`（粗但正确），或 (c) `invoke()` 在非主线程调用时显式 raise（强制 async）。AC-F12 用 `ThreadPoolExecutor` 实跑并发 `invoke()`，断言不抛 sqlite ProgrammingError。

### H5 — F06 "锁 IP + Host header" 破坏 SNI/虚拟主机/HTTPS 证书校验；重定向欠定义
`agent/mcp/tools_registry.py:208-271`

1. HTTPS 下 `urlopen` 到裸 IP URL + `Host` header 会破坏 TLS 证书校验（证书是 `example.com`，SNI 握手用 IP）→ 证书验证失败；虚拟主机路由到错误 vhost。设计未提 SNI/`ssl.SSLContext`/`server_hostname`。
2. `urllib` 重定向 handler 重解析 `Location`；相对 `Location`（RFC 7231 允许）需对请求 URL 解析；每次重定向 `urlopen` 仍 `getaddrinfo`（重定向上的 DNS 重绑定）。

**改法**：(a) 放弃 IP+Host，改**禁用重定向**（`HTTPRedirectHandler` raise）+ 连接后 socket 级校验 peer IP ∈ 已校验集合；或 (b) HTTPS 用 `httpx` 显式 `assert_hostname`/`server_hostname`。设计必须显式写 SNI/证书故事；AC 含相对重定向。

### H6 — F08 中文姓名误报辐射 + LLM-PII prompt 泄露
`agent/guardrails/pii.py`、`agent/eval/judge.py`

1. 机尾号 `B-\d{4}`、MSN `MSN \d+` 在 PHM 维修日志里是**运维标识符，不是 PII**。设计把"航空标识符"与 PII 混为一谈。护照 `E\d{8}` 默认开也风险高。
2. LLM-PII 走本地 Qwen3（即生成答案的同一模型），PII 文本进 judge 上下文，可能被 OTEL/sampler 记录（`capture.py` 生产 + `should_sample=True` 测试）——把要检测的 PII 持久化了。

**改法**：(a) 机尾/MSN 重分类为非 PII（或独立 `PII_DETECT_OPERATIONAL_IDS` flag）；(b) LLM-PII span 显式禁遥测（`trace_context` 加 `no_record`），设计需写明；(c) 测试断言 PII-judge 调用不被 inference sampler 捕获。

---

## MEDIUM

- **M1 F11**：`close()` 是死代码——grep 确认无人调 `get_hybrid_retriever().close()`；"实例 vs 类"对单例无实际差别，真 BUG 是 `max_workers=2` 全局上限。改法：`api/main.py` lifespan shutdown 加 `get_hybrid_retriever().close()`；AC 围绕 `max_workers` 可配 + shutdown hook。
- **M2 F15**：shim 删除安全（确认无外部 import），但设计"全文搜引用"未覆盖 `docs/**/*.md`、`AGENTS.md`/`CLAUDE.md` 代码块（`AGENTS.md:291` 有 `get_agent_harness()` 风格片段）。`test_no_legacy_skill_shims.py` 只断言文件不存在，抓不到悬空文档引用。改法：F15 PR 含对 docs/markdown 的 grep。
- **M3 F16**：两步拆分使 AC-F16 在 step 1 不可达——`Depends` 注入若端点体内仍 inline 调 getter，`dependency_overrides` 拦不住。AC-F16 只在**同一 PR 内全端点迁移**才可达。`create_app()` 还须把 `instrument_fastapi`、CORS、静态 mount、SPA catch-all 全移进去（设计影响清单漏了）。改法：F16 单一原子 PR。
- **M4 顺序**：F16 在 WP1 前，若 F16 改坏 conftest，WP1 的 F01 测试无法验证。改法：WP1 测试直接对 singleton getter（不经 HTTP client），与 F16 解耦。
- **M5 F13**：`pytest-benchmark` 是新外部依赖，违反 requirements §4"不引入新的外部依赖"。改法：用 `time.perf_counter` + 硬阈值断言，不加依赖。
- **M6 F18**：改 `_get_doc_id` 改变所有 doc id；缓存键不含 doc-id，部署后缓存服务旧融合结果直到 TTL。改法：部署时 bump cache-version 常量 / lifespan 启动清一次缓存。
- **M7 F22**："仅新文件 LFS"**不减少**现有 clone 体积（95MB 留在历史）。`git lfs migrate` 才减，但重写所有 SHA、破坏 `sync-to-mirror.yml`。改法：设计显式声明"默认路径不减现有 clone 体积，仅防未来；clone 体积缩减需团队拍板 migrate"。

## LOW
- **L1 F03**：纯文档+测试，可接受；但"键写权表"放哪未指明——确认放 `AGENTS.md §4.1`。
- **L2 F09**：`ast` 修复正确；确认 `abs`/`pow` 因字符白名单不可达（`a/b/s` 不在 `allowed`）。诊断对、修复对。
- **L3 F04**：确认重复 import；F04 的 AC"ruff check 通过"依赖 F23——跨 WP 依赖需注明。

## 进程/测试基建
- **P1 F24/F25**：`tests.yml` PR 跑最小 pip install（无 torch/ollama/model）；`self-hosted` runner 在 `eval-regression.yml` 被引用但是否注册/有 GPU 未验证。若 runner 不在，`requires_backend` 测试写了永远不跑=虚假信心。`test_system.py`（12KB 脚本式）转 pytest 工作量被低估。改法：编码 F24 前先验证 runner 健康；否则把 F24 降级为"写好+标记，nightly 按 runner 可用性触发"，AC-G3 显式条件化。
- **P2 F25**：SSE 的 Playwright 测试易 flaky；须指定等待策略（`waitForResponse`/CDP/JS 层 mock EventSource）。CI 须独立 Node job（setup-node/npm ci/build/起后端/test）。`web/playwright.config.ts` 不存在。
- **P3**：AC-G1 只跑 `tests/unit tests/e2e`，不含 `tests/api/integration`；`testpaths` 也只这两者。F24 须更新 `testpaths` 或 AC-G1 改 `-m "not requires_backend"`。

## 设计正确的地方（平衡）
- F01 根因诊断对（读侧 `BM25Retriever()` 构造）；仅修复过宽（见 C1）。
- F10 producer 侧修复对；仅漏消费侧（C2）。
- F15 shim 删除验证安全。
- F20 lazy import `ocr_engine.py:54` 已部分做；改可选 extra 低风险。
- F17 公开方法提取正确。
- F09 `ast` 修复正确。
- F11 正确识别 `max_workers=2` 瓶颈；仅漏生命周期关闭（M1）。
- F04/F03/F18/F19 诊断与代码一致。
