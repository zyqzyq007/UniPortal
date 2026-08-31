# 设计文档：bugfix-batch-1

> 方案文档。每个 finding 给出：现状 → 方案 → 影响面 → 降级/回滚 → 测试。
> 实施顺序遵循「依赖箭头」：F16(app factory) 先行，因其改变所有 e2e 的接线方式；
> F15(shim) 与 F20(deps) 次之；其余按 WP 顺序，每个 WP 独立 PR 可回滚。

## 修订记录

- **v2**：纳入批评者/辩护者评审（`review/critic.md`、`review/defender.md`）的全部
  Critical/High 修订：C1（F01 缓存失效+弃捷径+预热测试）、C2（F10 消费侧）、H1（F02 两通道守卫）、
  H2/H3（F05 RuntimeError+PYTEST_RUN+非 strip 比较）、H4（F12 边界锁）、H5（F06 禁重定向+peer-IP）、
  H6（F08 航空标识非人 PII+禁遥测）、M1（F11 close hook）、M3（F16 原子 PR）、M4（WP1 测试不经 client）、
  M5（perf_counter）、M6（F18 缓存版本）、M7（F22 体积声明）、P1（runner 先验）、P2（Playwright CI 形态）、
  P3（testpaths/AC-G1）。所有 Critical/High blocker 已解决，辩护者结论为"方案可辩护（经修订后）"。

## 0. 实施顺序与依赖

```
F16(app factory) ──┬─► F15(shim 删除, README)
                   ├─► WP1(F01..F04)  ← e2e 接线稳定后改检索/状态
                   ├─► WP2(F05..F10)  ← 独立
                   ├─► WP3(F11..F14)  ← F01 完成后改检索并发
                   ├─► WP4(F17..F19)  ← F15 完成后改契约/去重
                   └─► WP5(F20..F23)  ← 独立，影响部署
WP6(F24,F25) 贯穿全程：每个 WP 落地时补对应测试；F25(Playwright) 放最后（前端无大改）。
```

每个 WP = 一个 PR，独立可回滚。F16 与 WP1 因触及 e2e 基建，合并后需全量回归。

**顺序解耦（M4 修订）**：WP1 的 F01 一致性测试**直接对 singleton getter**（`get_bm25_retriever()`/
`get_hybrid_retriever()`）断言，**不经 HTTP client**——这样即便 F16 改坏 conftest，WP1 仍可独立验证，
不必强制 F16 先于 WP1。F16 与 WP1 的依赖关系因此从"硬序"降为"软序"（F16 先更优，但非阻塞）。

---

## WP1 正确性

### F01 BM25 双实例分歧 + 缓存失效（Critical, C1 修订）
- **现状**：`core/retrieval/hybrid_retriever.py` 的 `sparse_retriever` 属性 `self._sparse_retriever = BM25Retriever()`
  （新建），而 `api/routers/documents.py` 增删改作用于 `get_bm25_retriever()` 单例。两条路径是不同对象。
  **写路径其实已调单例 `add_documents`（`documents.py:357`），BUG 纯在读路径**。另：检索结果缓存
  （`hybrid_retriever.py:185-194`）键为 `(query, filter, top_k)`，无失效，上传后会服务旧答案。
- **方案**（按 C1，最小且正确）：
  1. `sparse_retriever` 属性改为返回 `get_bm25_retriever()` 单例（一行核心修复）。
  2. **删除** `_ensure_sparse_indexed` 里"引导后标记已建索引避免重载"的捷径——引导仅在单例为空时
     重跑，**永不假设新鲜**（否则单例引导一次后短路，后续上传被吞错就永久陈旧，正是回归路径）。
  3. **缓存失效**：documents 路由 `add_documents`/`remove_by_source` 后清 `get_retrieval_cache()`
     （或引入 index-version 计数器，每次变更自增并并入缓存键）。推荐 index-version 计数器（O(1)、
     不需遍历清缓存），`core/retrieval/cache.py` 暴露 `bump_version()`，缓存键含 version。
- **影响面**：`core/retrieval/hybrid_retriever.py`（属性 + 引导逻辑）、`core/retrieval/cache.py`
  （version 计数器）、`api/routers/documents.py`（增删后 `bump_version()`）、`core/retrieval/bm25_retriever.py`
  （如缺 `remove_*` 方法补齐——已确认有 `remove_by_source`）。
- **降级**：单例/缓存不可用时仍回退 dense-only（既有逻辑不变；version 计数器失败则降级为清全缓存）。
- **回滚**：还原属性为新建实例（但重开 BUG）。
- **测试**：`tests/unit/test_bm25_consistency.py`——**预热缓存场景**：先 `retrieve(q)` 填缓存 →
  documents 上传新文档（触发 `bump_version`）→ 同进程 `get_hybrid_retriever().retrieve(q)` 命中新文档；
  删除后不再命中。两个用例覆盖 index-version 失效路径。

### F02 grade 条件边两通道守卫（High, H1 修订）
- **现状**：`grade` 作为 conditional edge，`_skill_to_conditional`（`orchestrator.py:430-497`）有
  **两条**状态丢失通道：(1) `before_increments`（line 445）计算后被丢弃；(2) grade 技能自身
  `result.to_state_update()` 永不应用，只用 `result.next_action`（line 464）。代码注释说当前良性
  （grade 仅返回 metadata），但无运行时守卫，未来开发者给 GradeSkill 加 `state_updates` 会被静默丢弃。
- **方案**（保守，不转普通节点以免改拓扑）：守卫放进 **`_skill_to_conditional` 自身**（非
  `LifecycleManager`，因后者只覆盖通道 1）。在 conditional 函数返回路由键前，断言：
  (a) `before_increments` 无 `shared_state`/非空键；(b) `result` 不带 `state_updates`/`shared_state`。
  违反则 `log.error("[grade-conditional-guard] ...")` 并丢弃，附文件级注释说明「若需 grade 写状态，
  转普通节点」。log-only，不改路由。
- **影响面**：`agent/harness/orchestrator.py`（`_skill_to_conditional`）。
- **降级**：守卫只 log，不改路由。
- **测试**：`tests/unit/test_lifecycle_grade_guard.py`——(1) 注册返回增量的 grade before-hook，
  断言增量未进状态且有 error 日志；(2) mock 一个带 `state_updates["shared_state"]` 的 GradeSkill
  result，断言同样被守卫捕获。覆盖两通道。

### F03 shared_state 浅合并契约显式化（High）
- **现状**：`merge_shared_state` 浅合并，同键整键覆盖；契约只在注释里。
- **方案**：不改语义（避免破坏现有生产者/消费者），但在 `AgentState` docstring 与
  `AGENTS.md` §4.1 已有的基础上，新增 `tests/unit/test_shared_state.py::test_shallow_merge_overwrites_whole_key`
  固化语义；为最关键的列表型键（`retrieved_contexts`/`sources`/`relevant_memories`）在
  producer 侧文档化「谁拥有写权」。
- **影响面**：测试 + 文档。
- **测试**：见上。

### F04 state.py 重复 import（Low）
- **现状**：`agent/context/state.py:18-19` 两行 `from utils.log_utils import log`。
- **方案**：删重复行；加 `pyproject.toml` 的 ruff 配置 + pre-commit（见 F23 同批）作为门禁。
- **测试**：`ruff check` 通过。

---

## WP2 安全

### F05 admin 启动校验 + 常量时间比较（High, H2/H3 修订）
- **现状**：`api/routers/admin.py` 未校验生产是否设 key；`x_admin_key.strip() != configured` 用 `==`
  且对 configured key `.strip()`（长度泄露 + 静默改写）。
- **方案**：
  1. `require_admin` 用 `hmac.compare_digest(x_admin_key.encode(), configured.encode())`；
     **不在比较时 strip**（config-load 时校验 configured key 无首尾空白、长度 ≥32，否则启动报错）。
  2. lifespan fail-fast：`(ADMIN_API_KEY 未设) AND (ALLOWED_ORIGINS 仍本地默认) AND (非 testmode)` 时
     **抛 `RuntimeError`（非 `sys.exit`）**，uvicorn 记一次日志后非零退出，避免 Docker restart-loop。
  3. test-skip：`os.environ.get("PYTEST_RUN") == "1"`，在 `tests/conftest.py` **顶层**（collection 时）
     设置，保证 lifespan 进入前已置位。`deploy.sh` 文档 `restart_policy.condition: on-failure` + max-attempts。
- **影响面**：`api/routers/admin.py`、`api/main.py`、`tests/conftest.py`（顶层设 PYTEST_RUN）、`deploy.sh`。
- **降级**：testmode 跳过校验，不破坏 e2e。
- **回滚**：移除 lifespan 校验块 + 还原 `!=`。
- **测试**：`tests/unit/test_admin_auth.py`——断言走 `compare_digest`（mock 验证调用）+ configured key
  合法性校验；`tests/e2e/test_startup_guard.py`——模拟生产 env（清 PYTEST_RUN、默认 origins）断言启动
  抛 RuntimeError；testmode 下不断言不抛。

### F06 SSRF 禁重定向 + peer-IP 校验（High, H5 修订）
- **现状**：`_ssf_blocked` 解析 → `urlopen` 的 TOCTOU；`urlopen` 默认跟随重定向可被 302 引到内网。
- **方案**（按 H5，放弃会破坏 TLS 的 IP+Host 方案）：
  1. **禁用重定向**：自定义 `urllib.request.HTTPRedirectHandler`/`HTTPSHandler` 子类，`redirect_request`
     返回 `None`（不跟随），改为收集首跳响应；若业务确需重定向，逐跳重新 `_ssf_blocked` 并重锁。
  2. **peer-IP 校验**：连接后从 socket 取 peer IP，校验 ∈ `_ssf_blocked` 解析并校验过的地址集合；
     不匹配则中断。用 `http.client.HTTPConnection` 手动 connect 或 `urllib3` 的 `HTTPResponse` 暴露的
     `connection.sock.getpeername()`。
  3. HTTPS 显式 `ssl.SSLContext` + `server_hostname=原host`（保 SNI 与证书校验），**不用裸 IP 连**。
  4. 相对 `Location`（RFC 7231）解析：`urllib.parse.urljoin(request_url, location)`。
- **影响面**：`agent/mcp/tools_registry.py`。
- **降级**：工具默认关闭；修复后行为更严，不破坏合法调用。无法锁 IP 时**要求** `HTTP_TOOL_ALLOWED_HOSTS`。
- **测试**：`tests/unit/test_ssrf.py` 扩展——mock 302→内网被拒（不跟随）；peer-IP 与解析集不符被拒；
  HTTPS 正常 host 通过（SNI 不破）；相对重定向解析正确。

### F07 中文注入模式（High）
- **现状**：`INJECTION_PATTERNS` 全英文。
- **方案**：补充中文模式：`忽略(以上|前面|之前|上面)(的)?(指令|规则|提示|内容)`、
  `无视(以上|前面)…`、`你现在是(DAN|开发者模式|无限制)`、`越狱`、`进入.*模式`（谨慎，配负面测试）、
  `扮演.*角色`、`不要遵守`、`输出.*系统提示` 等。保留 `re.IGNORECASE`。
- **影响面**：`agent/guardrails/prompts.py`、`tests/unit/test_input_guardrail.py`。
- **测试**：中文样本（"忽略以上指令""你现在是DAN""越狱"）被 BLOCK；正常 PHM 问题（含「模式」「规则」
  字样但不操控）不被误杀（负面测试）。

### F08 PII 航空分级 + opt-in LLM 通路（禁遥测）（High, H6 修订）
- **现状**：PII 仅 id/phone/bank/email/ip；无航空场景；无 LLM 改写式 PII 通路。
- **方案**（按 H6，分级 + 禁遥测）：
  1. **人 PII**（默认开）：护照号 `E\d{8}` 等；保留既有 id/phone/bank/email/ip。
  2. **航空运维标识非 PII**：机尾号 `B-\d{4}`、MSN `MSN \d+`、航班号 **重分类为非人 PII**，独立 flag
     `PII_DETECT_OPERATIONAL_IDS`（默认关），文档警示其在维修日志里常为合法内容。中国姓名（百家姓+单字）
     高误报，`PII_DETECT_NAMES` 默认关。
  3. **opt-in LLM 通路**：`PII_LLM_PASS=true` 时，正则无命中后用本地 Qwen3 判定「是否含人 PII」。
     **该 span 显式禁遥测**：`trace_context` 加 `no_record=True`（OTel 不采样），且 inference sampler
     对 PII-judge 调用跳过捕获（`capture.py` 检测调用栈来源）。复用 `judge.py` 熔断；不可用→仅正则。
- **影响面**：`agent/guardrails/pii.py`、`agent/guardrails/prompts.py`、`agent/guardrails/types.py`、
  `core/tracing/opentelemetry.py`（`no_record` 支持）、`agent/eval/capture.py`（跳过 PII-judge）。
- **降级**：LLM 不可用 → 仅正则。
- **测试**：`tests/unit/test_pii.py`——护照号命中；机尾号默认不命中（开 flag 才命中）；LLM 通路熔断降级；
  **断言 PII-judge 调用不被 inference sampler 捕获**（防泄露）。

### F09 calculator eval → ast（High）
- **现状**：`UtilityToolsServer.calculate` 用字符白名单 + 函数名剥离 + `eval()`；`abs`/`pow` 不可达。
- **方案**：改 `ast.parse` + `ast.NodeVisitor` 白名单（仅 `Expression/BinOp/UnaryOp/Constant/Call(白名单函数)`），
  手写求值（不调 `eval`/`compile` exec）；恢复 `abs`/`pow`/新增 `min`/`max`/`round`。
- **影响面**：`agent/mcp/tools_registry.py`、`tests/unit/test_calculator.py`。
- **测试**：合法表达式返回正确值；注入尝试（`__import__`、属性访问 `os.system`、`x.__class__`）被拒；
  `abs(-5)`→5、`min(1,2)`→1。

### F10 PII SANITIZE 不覆盖 ESCALATE + 消费侧应用脱敏（Critical, C2 修订）
- **现状**：`output_guardrails.py:236` 的 `return` 丢弃 `worst`（ESCALATE）。**消费侧**
  `manager.py:142-149` ESCALATE 分支从不读 `sanitized_content` → 即便 producer 返回 ESCALATE+脱敏，
  `last_msg.content` 仍原样下发含 PII 幻觉。
- **方案**（按 C2，producer + consumer 两侧）：
  1. **producer**（`output_guardrails.py`）：PII 分支不再直接 `return`；把脱敏 `sanitized_content`
     合并进 `worst`——若已有 ESCALATE，保留 ESCALATE 动作 + metadata 记 pii redaction，脱敏内容附在
     `worst.sanitized_content`；若无 ESCALATE，则 SANITIZE（原行为）。
  2. **consumer**（`manager.py:142-149`）：ESCALATE 分支当 `guard_result.sanitized_content` 存在时
     也写 `last_msg.content = sanitized_content`，保证升级路径上下发的 message 已脱敏。
- **影响面**：`agent/guardrails/output_guardrails.py`、`agent/guardrails/manager.py`、
  `tests/unit/test_output_guardrail.py`。
- **测试**：含 PII 的幻觉答案 → 动作 ESCALATE + sanitized_content 已脱敏 + metadata 含 pii；
  **断言实际下发的 `last_msg.content` 含 `[已脱敏:...]` 而非原始 PII**（不只断言 GuardrailResult 字段）。

---

## WP3 并发/性能

### F11 ThreadPoolExecutor 全局瓶颈 + close hook（Medium, M1 修订）
- **现状**：`_executor = ThreadPoolExecutor(max_workers=2)` 是类属性，跨实例跨请求共享，max=2。
  核心问题是 `max_workers=2` 全局上限（单例下"实例 vs 类"无实际差别）。另：grep 确认无人调
  `get_hybrid_retriever().close()`，故即便加 shutdown 也是死代码。
- **方案**（按 M1）：
  1. `max_workers` 由 `RETRIEVAL_PARALLEL_WORKERS`（默认 4）配置；executor 仍为实例属性（语义清晰）。
  2. `HybridRetriever.close()` 内 `self._executor.shutdown(wait=False)`。
  3. `api/main.py` lifespan shutdown **新增** `get_hybrid_retriever().close()`（消除死代码）。
  4. 异步路径已在 `run_in_executor(None,...)`（默认无界池），**显式不动并文档化**（非瓶颈）。
- **影响面**：`core/retrieval/hybrid_retriever.py`、`api/main.py`。
- **降级**：`_dense/_sparse_retrieve` 的 try/except 不动（I9）。
- **测试**：`tests/unit/test_retrieval_concurrency.py`——并发 N 个 retrieve 不互相阻塞（阈值断言）+
  `close()` 后 executor 已 shutdown。

### F12 sync invoke() 边界锁（High, H4 修订）
- **现状**：同步 sqlite `check_same_thread=False` 共享连接无锁；`SqliteSaver(conn)` 接管连接，
  在其内部 `put/get` 写——harness 侧连接级锁 `SqliteSaver` 不会获取，什么都不串行化（错层）。
- **方案**（按 H4，选 invoke 边界锁）：在 `invoke()`/`stream()` 用**进程级 `threading.Lock`** 包
  `self.graph.invoke(...)`/`self.graph.stream(...)`（粗但正确，串行化整个图调用）。docstring 加并发警告
  「生产多 worker 用 async」。**不删 sync**（CLI/脚本依赖）。
- **影响面**：`agent/harness/orchestrator.py`（`invoke`/`stream` 加 `self._sync_invoke_lock`）。
- **降级**：加锁后吞吐略降但正确。
- **测试**：`tests/unit/test_sync_checkpoint_concurrency.py`——`ThreadPoolExecutor` 并发多线程 `invoke()`，
  断言不抛 sqlite ProgrammingError（`sqlite3` 线程错）。

### F13 缓存 deepcopy 基准（perf_counter）（Medium, M5 修订）
- **现状**：缓存写入 `copy.deepcopy(documents)`（修复了浅拷贝泄漏），开销未量化。
- **方案**（按 M5，不引入新依赖）：用 `time.perf_counter` 写 `tests/perf/test_cache_deepcopy.py`，
  断言 deepcopy P95 < 阈值（如 10 docs < 5ms，按实测定）。超阈值则改「Document 浅拷贝 + 新 metadata dict」
  （返回时 `copy.copy(doc)` + `dict(doc.metadata)`），不达标则保 deepcopy。**不用 `pytest-benchmark`**
  （违反 requirements §4"不引入新的外部依赖"）。
- **影响面**：`core/retrieval/hybrid_retriever.py`、`core/retrieval/cache.py`、`tests/perf/`。
- **测试**：`perf_counter` 基准 + 既有 cache 隔离测试（`test_stage23.py`）保持绿。

### F14 trace 隔离并发测试守卫（Medium）
- **现状**：contextvar trace 隔离依赖 LangGraph 传播，无测试守卫。
- **方案**：`tests/unit/test_trace_isolation.py`——并发 N 个 `ainvoke`，断言每个 run 的 trace 互不串。
- **影响面**：测试。

---

## WP4 架构/可维护

### F15 删技能 shim + 更新 README + 文档 grep（Critical 可维护性, M2 修订）
- **现状**：`agent/skills/*_skill.py` shim 与目录技能并存；README 描述过时扁平布局。grep 确认无第一方
  代码 import shim（orchestrator 与 `__init__.py` 均从目录导入）。
- **方案**（按 M2，含文档扫描）：删除 6 个 shim（`agent_skill.py`/`retrieve_skill.py`/`grade_skill.py`/
  `rewrite_skill.py`/`generate_skill.py`/`intent_skill.py`）；**全文 grep** `docs/**/*.md`、`*.md`（含
  `AGENTS.md`/`CLAUDE.md`/`README.md`）的 shim 模块路径引用并改向目录；重写
  `agent/skills/README.md`「Current Skills」表指向 `agent/skills/<name>/skill.py`。
- **影响面**：`agent/skills/`、`agent/skills/README.md`、可能引用的文档代码块。
- **回滚**：git revert。
- **测试**：`import api.main` + 全 e2e 绿；`tests/unit/test_no_legacy_skill_shims.py` 断言 6 个 shim
  文件不存在；额外用 `grep -rn "*_skill" docs/ *.md` 作为 PR 检查脚本（`scripts/check_no_shim_refs.sh`）。

### F16 app factory（原子 PR）（High, M3 修订）
- **现状**：`api/main.py` 模块级 `app`；路由内联 import 单例；conftest 必须 monkeypatch 源模块。
  `Depends` 注入若端点体内仍 inline 调 getter，`dependency_overrides` 拦不住——两步拆分使 AC-F16 不可达。
- **方案**（按 M3，**单一原子 PR**）：
  1. 引入 `create_app(settings) -> FastAPI`，把**所有**当前模块级逻辑移进 factory：CORS、
     `TracingMiddleware`/`ErrorHandlerMiddleware`、`include_router`、`instrument_fastapi(app)`、
     健康检查路由、静态 `web/dist` mount、SPA catch-all。
  2. **全端点迁移** `Depends`：`get_harness_dep`/`get_retriever_dep`/`get_llm_dep`/`get_session_memory_dep`，
     端点签名声明依赖，**移除体内 inline `get_xxx()` 调用**。
  3. `api/main.py` 保留 `app = create_app()` 供 uvicorn。
  4. `tests/conftest.py` 改用 `app.dependency_overrides[...] = fake`，**删除**源模块 monkeypatch。
- **影响面**：`api/main.py`、所有 `api/routers/*.py`、`tests/conftest.py`。
- **风险**：单 PR 改动大，必须全量 e2e 回归；不做两步拆分（会留半迁移态，AC 不可达）。
- **回滚**：整个 PR revert（原子）。
- **测试**：既有 e2e 全绿；新增 `tests/e2e/test_app_factory.py`——注入 fake 单例跑全链路，**且新增一个
  虚拟路由**不需改 conftest 即可被 e2e 覆盖（证明 AC-F16「新路由不再需改 monkeypatch 列表」）。

### F17 grounding 公开契约（Medium）
- **现状**：`grounding_guardrail` 调 `judge._entail`/`_aentail`（私有）。
- **方案**：在 `LLMJudge` 暴露 `entail(claim, context) -> Optional[JudgeVerdict]` 与
  `aentail(...)`，内部委托既有私有方法；guardrail 改调公开方法。
- **影响面**：`agent/eval/judge.py`、`agent/guardrails/grounding_guardrail.py`。
- **测试**：既有 grounding 测试绿。

### F18 `_get_doc_id` hash 全文 + 缓存版本 bump（Medium, M6 修订）
- **现状**：仅 hash 前 500 字符，共享前缀文档在 RRF 被合并。改全文 hash 会改所有 doc id，缓存键
  `(query,filter,top_k)` 不含 doc-id → 部署后缓存服务旧融合结果直到 TTL。
- **方案**（按 M6）：改 hash 全文（`page_content` 全量，或 `(source, 全文)`）；**部署时 bump 缓存版本**
  ——与 F01 的 index-version 计数器复用同一机制，或 lifespan 启动清一次 `get_retrieval_cache()`。
- **影响面**：`core/retrieval/hybrid_retriever.py`、`core/retrieval/cache.py`。
- **测试**：`tests/unit/test_rrf_dedup.py`——共享 500 字符前缀但内容不同的两文档产生 2 个独立 RRF 条目。

### F19 sync/async 检索去重（Low）
- **现状**：retrieve/aretrieve、dense/_adense 等成对重复，缓存写需手工双处同步。
- **方案**：抽 `_retrieve_pipeline(query, filter_expr, top_k) -> FusedResult`（纯逻辑，无 async），
  async 路径用 `asyncio.to_thread` 调它；缓存读写抽 `_cache_get/_cache_put` 单点。
- **影响面**：`core/retrieval/hybrid_retriever.py`。
- **测试**：既有检索测试绿 + 缓存隔离测试绿。

---

## WP5 依赖/发布

### F20 paddle 改可选（High）
- **现状**：`pyproject.toml` 把 `paddlepaddle`/`paddleocr` 列为无条件依赖。
- **方案**：移到 `[project.optional-dependencies] ocr = ["paddlepaddle>=3.3.1", "paddleocr>=3.7.0"]`；
  `documents/ocr_engine.py` 的 paddle 导入改为延迟 + 友好报错（「请 uv sync --extra ocr」）；
  `deploy.sh` 默认装 ocr extra（或按 flag）；`run.sh` 同步。
- **影响面**：`pyproject.toml`、`documents/ocr_engine.py`、`deploy.sh`、`run.sh`。
- **测试**：`uv sync`（无 extra）后 `import api.main` 不报 paddle 缺失；OCR 单元测试在装了 extra 时跑。

### F21 langchain 版本上限 + contextvar 守卫（High）
- **现状**：langchain/langgraph 仅 `>=`，无上限；trace 隔离依赖 contextvar 传播。
- **方案**：加兼容版本上限（如 `langgraph>=1.0.0,<2.0.0`、`langchain>=1.0.0,<2.0.0`，按当前稳定线）；
  F14 的并发测试作为升级守卫；`requirements.txt`/`uv.lock` 同步。
- **影响面**：`pyproject.toml`、`requirements.txt`。
- **测试**：F14 守卫。

### F22 bge 模型文件 LFS + 体积声明（Medium, M7 修订）
- **现状**：`models/local_models/bge-small-zh-v1.5/model.safetensors`（95MB）被 git 追踪。
- **方案**（按 M7）：`.gitattributes` 配 `model.safetensors filter=lfs` 对**新增**模型文件启用；
  老文件不 migrate（`git lfs migrate --everything` 重写所有 commit SHA，破坏 `sync-to-mirror.yml` 与
  inference 记录里的 `git_commit` 字段，需团队拍板）。
- **影响面**：`.gitattributes`、文档（`README.md`/`AGENTS.md` 说明）。
- **体积声明**（必须在文档显式写）：**默认路径不减现有 clone 体积（95MB 留在历史），仅防未来新增大文件**。
  clone 体积缩减需团队决定是否 `git lfs migrate`，本批次不做。
- **测试**：`.gitattributes` 含规则；新提交的 `.safetensors` 走 LFS（`git check-attr filter model.safetensors`）。

### F23 CHANGELOG + ruff/pre-commit（Medium/Low）
- **方案**：新建 `CHANGELOG.md`（Keep a Changelog 格式，从本批次起记）；`pyproject.toml` 加
  `[tool.ruff]` 规则 + `.pre-commit-config.yaml`（ruff + 重复 import 检测）；版本从 0.1.0 起按 semver。
- **影响面**：仓库根配置。
- **测试**：`ruff check .` 通过（含 F04 修复）。

---

## WP6 测试基建

### F24 真实后端 + 真实 judge 飞轮进 CI（High, P1/P3 修订）
- **现状**：`tests/api/`、`tests/integration/` 不在 CI（`testpaths` 只含 unit/e2e）；飞轮 e2e 用 fake judge。
  `eval-regression.yml` 引用 `self-hosted` runner 但未验证其注册/有 GPU/Ollama；`test_system.py` 是
  12KB 脚本式代码，转 pytest 工作量大。
- **方案**（按 P1/P3）：
  1. **先验 runner**：编码 F24 前，先跑一次性 workflow 验证 `self-hosted` runner 注册且有 Ollama+Qwen3。
     若不可用，F24 降级为"测试写好+标记，nightly 按 runner 可用性触发"，AC-G3 显式条件化（不谎报覆盖）。
  2. `tests/api`、`tests/integration` 关键脚本改写为 pytest（保留 `urllib`，加 `@pytest.mark.requires_backend`）；
     `test_system.py` 分拆成多个 pytest 用例。
  3. 新增 `tests/e2e/test_flywheel_real_judge.py`（`requires_ollama`）：真实 judge 跑 replay 样本。
  4. **testpaths/AC-G1（P3）**：`pyproject.toml [tool.pytest.ini_options]` 加 `requires_backend`/`requires_ollama`
     marker；默认 `pytest` 加 `-m "not requires_backend and not requires_ollama"`（PR 门禁），
     nightly/self-hosted 不带过滤跑全集。AC-G1 同步改为 `pytest tests/unit tests/e2e -m "not requires_*"`。
- **影响面**：`pyproject.toml`、`.github/workflows/tests.yml`、`eval-regression.yml`、`tests/api/`、
  `tests/integration/`、`tests/e2e/test_flywheel_real_judge.py`。
- **测试**：CI 配置本身；PR 上 `requires_*` 用例不被收集（或 skip）。

### F25 Playwright 前端 E2E（High, P2 修订）
- **现状**：无浏览器自动化；SSE 测试易 flaky；`web/playwright.config.ts` 不存在；CI 须独立 Node job。
- **方案**（按 P2）：
  1. `web` 加 `@playwright/test` devDep + `web/playwright.config.ts`（`webServer` 指向后端启动脚本）。
  2. `tests/e2e_ui/` spec：chat 发问收答、文档上传、会话切换、点赞/点踩反馈。**SSE 流式**用 JS 层 mock
     `EventSource` 求稳（确定性），或 `page.waitForResponse` + 固定等待；不在字节边界上断言。
  3. **独立 Node CI job** `.github/workflows/e2e-ui.yml`：`actions/setup-node` → `npm ci` → `npm run build`
     → 起后端（fake 模式）→ `npx playwright test`。
  4. `web/package.json` 加 `test:e2e` 脚本。
- **影响面**：`web/package.json`、`web/playwright.config.ts`、`tests/e2e_ui/`、`.github/workflows/e2e-ui.yml`。
- **测试**：Playwright spec 自身；CI 绿。

---

## 测试矩阵汇总（本批次新增）

| 测试 | 类型 | 覆盖 findings |
|------|------|----------------|
| `tests/unit/test_bm25_consistency.py` | unit | F01 |
| `tests/unit/test_lifecycle_grade_guard.py` | unit | F02 |
| `tests/unit/test_shared_state.py`（扩展） | unit | F03 |
| `tests/unit/test_admin_auth.py`（扩展） | unit | F05 |
| `tests/e2e/test_startup_guard.py` | e2e | F05 |
| `tests/unit/test_ssrf.py`（扩展） | unit | F06 |
| `tests/unit/test_input_guardrail.py`（扩展） | unit | F07 |
| `tests/unit/test_pii.py`（扩展） | unit | F08 |
| `tests/unit/test_calculator.py` | unit | F09 |
| `tests/unit/test_output_guardrail.py`（扩展） | unit | F10 |
| `tests/unit/test_retrieval_concurrency.py` | unit | F11 |
| `tests/unit/test_sync_checkpoint_concurrency.py` | unit | F12 |
| `tests/perf/test_cache_deepcopy_benchmark.py` | perf | F13 |
| `tests/unit/test_trace_isolation.py` | unit | F14, F21 |
| `tests/unit/test_no_legacy_skill_shims.py` | unit | F15 |
| `tests/e2e/test_app_factory.py` | e2e | F16 |
| `tests/unit/test_rrf_dedup.py` | unit | F18 |
| `tests/e2e/test_flywheel_real_judge.py`（requires_ollama） | e2e | F24 |
| `tests/e2e_ui/*.spec.ts`（Playwright） | UI e2e | F25 |

## 回滚策略

- 每个 WP 独立 PR；PR 标题带 `[WPx]`，描述链接本设计文档与 review 报告。
- F16、F20、F22 涉及基建/部署，合并后单独跑一次 `deploy.sh --build-offline-bundle` 验证。
- 任一 WP 回滚不影响其他 WP（依赖箭头已隔离）。

## 风险与缓解

- **F16 app factory 改动面大**：分两步（先 factory+Depends，再逐路由迁移），每步独立回归。
- **F22 git history 重写**：默认不 migrate 历史，仅新文件 LFS；migrate 需团队拍板。
- **F08 姓名检测误报**：默认关闭，env 开启，文档警示。
- **F20 部署脚本**：deploy.sh 默认装 ocr extra，避免离线包丢 OCR 能力。
