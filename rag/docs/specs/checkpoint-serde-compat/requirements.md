# Checkpoint Serde 兼容性修复 — 需求

## 问题陈述

端到端 eval(`scripts/run_eval.py`)在当前 `uv.lock` 锁定的依赖组合下**全部失败**:15/15 用例 ERROR,`average_score=0.000`,LLM judge 从未运行。根因是
`langgraph-checkpoint-sqlite 2.0.10` 与 `langchain-core 1.2.30` 的 serde API 不兼容
——sqlite saver 调用已被移除的 `JsonPlusSerializer.dumps()`/`.loads()`,而新版本只
暴露 `dumps_typed()`/`loads_typed()`。`SqliteSaver.put()` 抛 `AttributeError`,
整个 Thinking-mode graph 无法执行。

现有代码在异步路径(`astart()`)打了 `is_alive` + `dumps` 两处 monkeypatch 绕过,但
同步路径(`_setup_checkpointing()`/`invoke()`)完全没有 shim,且 shim 只补 `dumps`
未补 `loads`,异步路径在 `.loads(metadata)` 处仍会二次崩溃。`run_eval.py` 走同步
`harness.invoke()`,直接撞墙。

附带安全维度:当前锁定的 `langgraph-checkpoint 2.0.10` 受 CVE-2025-64439
(JsonPlusSerializer 反序列化 RCE,CVSS 9.8)、CVE-2025-67644(checkpointer SQLi)、
CVE-2026-27794(缓存层 RCE)影响。

## 本质需求 vs 表面需求

- **表面需求**:"benchmark 跑不出分"。审查发现真实瓶颈分两层:① pipeline 根本跑
  不通(本 spec);② 跑通后的检索/生成质量问题(jieba 缺失、英文 reranker、HyDE 未
  接线等,后续 Stage A-D)。
- **本质需求**:端到端 graph 的 checkpointer MUST 在当前依赖栈下正常序列化/反序列
  化会话状态,使 `invoke()`/`ainvoke()` 返回有效结果而非异常,从而让 eval 能产出可
  量化的真实得分基线,为后续优化提供度量靶子。同时顺带闭合已知的 checkpointer RCE
  类 CVE。

## 范围

**做**:
- 对齐 `langgraph-checkpoint-sqlite` 到 3.1.0(改用 `dumps_typed`/`loads_typed` +
  `json.dumps`/`json.loads`),`langgraph-checkpoint` 维持 4.x(实锁 4.1.1)。
- 删除 `astart()` 里两处过时 monkeypatch(`is_alive` + `_dumps_shim`)。
- 补齐持久化契约缺口:`checkpoint_path` 提升为模块级 `DEFAULT_CHECKPOINT_PATH`
  + `field(default_factory=...)` 延迟解析,使 `tests/conftest.py` 可重定向(§10)。
- 新增 regression test 覆盖同步/异步两条 checkpoint 路径(含非 gated 真实编译图)。
- 闭合 CVE-2025-64439 / CVE-2025-67644 / CVE-2026-27794;并强制 strict msgpack
  反序列化(`_enable_strict_msgpack_deserialization`)闭合默认 permissive 的 msgpack
  RCE 面(critic F-CS-06)。
- 约束 `aiosqlite<1.0`(F-CS-01),防 `_thread` 私有属性在 1.0 重构时击穿异步 saver。

**不做**:
- 检索栈优化(jieba、中文 reranker、HyDE 接线)——Stage A/B。
- 生成质量优化(thinking token 预算、grade schema)——Stage C。
- eval 数据集补全(golden context_ids、intent 提取)——Stage D。
- 不改变 graph 节点逻辑、不改 shared_state 键、不改 REST/CLI/env 契约。

## 非功能要求

- **离线/气隙**:`langgraph-checkpoint-sqlite 3.1.0` 引入新传递依赖 `sqlite-vec`(原生 C
  扩展,实锁 0.1.9),MUST 预下载该 wheel 并确认目标机 glibc/平台匹配(回归测试
  `test_sqlite_vec_importable_and_native_loadable` 固化)。3.1.0 本身是已发布稳定 wheel,
  可预下载。
- **降级**:checkpointer 初始化失败时仍维持现有 `MemorySaver` fallback(`_setup_checkpointing`
  的 `except ImportError` 分支不变)。
- **可逆性**:升级仅移动 `pyproject.toml` 版本上界,`uv.lock` 可回退;checkpoint 是
  会话临时态,历史 db 读不出时可重建,无不可逆数据损失。

## EARS 验收条件

- **REQ-CS-001** [根因]: WHEN `AgentHarness.invoke(question, thread_id=...)` 被调用,
  THE SYSTEM SHALL 正常返回包含 `messages` 的 dict,SHALL NOT 抛
  `AttributeError: ... no attribute 'dumps'`。
- **REQ-CS-002** [异步路径]: WHEN `await harness.astart()` 后 `await harness.ainvoke(...)`
  被调用,THE SYSTEM SHALL 正常返回结果 dict,SHALL NOT 抛 serde 相关异常。
- **REQ-CS-003** [依赖对齐]: THE pyproject SHALL 声明
  `langgraph-checkpoint-sqlite>=3.1.0,<4.0.0`,且 `langgraph-checkpoint` 维持
  `>=4.0.0,<5.0.0`(实锁 4.1.1)。`langgraph` 主版本不动(仍 1.1.x)。
- **REQ-CS-004** [安全]: THE SYSTEM SHALL 使用已闭合 CVE-2025-64439 /
  CVE-2025-67644 / CVE-2026-27794 的 checkpoint 版本(即 sqlite-saver 3.1.0 +
  checkpoint 4.1.x)。
- **REQ-CS-005** [同步 regression]: THE test suite SHALL 包含一条用例,真实构造
  harness 并同步 `invoke()`,断言不抛 + 返回 dict;该用例 SHALL 在升级前失败(红)、
  升级后通过(绿)。
- **REQ-CS-006** [异步 regression]: THE test suite SHALL 包含一条用例,真实
  `astart()` + `ainvoke()`,断言不抛 + 返回正常;红绿时序同 REQ-CS-005。
- **REQ-CS-007** [monkeypatch 清除]: THE `JsonPlusSerializer` 类 SHALL NOT 被本仓库
  代码注入 `dumps` 属性(确认升级后不再需要、且无残留 shim)。
- **REQ-CS-008** [持久化契约]: `agent.harness.orchestrator` SHALL 暴露模块级
  `DEFAULT_CHECKPOINT_PATH` 属性,`HarnessConfig.checkpoint_path` 默认值引用它,
  使 `tests/conftest.py tmp_data_dir` 可 `monkeypatch.setattr` 重定向。
