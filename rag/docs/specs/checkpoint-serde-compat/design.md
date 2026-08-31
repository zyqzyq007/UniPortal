# Checkpoint Serde 兼容性修复 — 设计

## 1. 根因链(逐环验证)

```
run_eval.py:144  harness.invoke(query, thread_id=...)        ← 同步路径
        │
orchestrator._setup_checkpointing()  L595-612                ← 同步,无任何 shim
        │  sqlite3.connect(checkpoint_path)
        └─ SqliteSaver(conn)  L608
                │  graph 执行时 langgraph 调 saver.put()
                └─ sqlite/__init__.py:415  self.jsonplus_serde.dumps(metadata)
                        └─ AttributeError: 'JsonPlusSerializer' object has no attribute 'dumps'
```

三个相互印证的事实:

1. **API 错配**:`langgraph-checkpoint-sqlite 2.0.10` 用旧 `.dumps()`/`.loads()`
   (`sqlite/__init__.py:267, 360, 415` 三处);`langgraph 1.1.6` + `langchain-core 1.2.30`
   的 `JsonPlusSerializer` 只有 `.dumps_typed()`/`.loads_typed()`(实跑
   `hasattr` 确认 `dumps=False, loads=False`)。
2. **现有 shim 不完整**:异步路径 `astart()`(L641-663)有 `is_alive` + `_dumps_shim`
   monkeypatch,但:① 同步路径 `_setup_checkpointing()`(L595-612)**完全没有 shim**;
   ② shim 只补 `dumps` **未补 `loads`**,异步路径在 L267/L360 仍会炸。
3. **基线后果**:端到端 eval 15/15 失败,avg=0.000,judge 从未运行。检索 benchmark
   (`run_benchmark.py`)不经 graph,其基线有效;**端到端真实得分目前为空**。

## 2. 版本约束现状与升级范围

`pyproject.toml:11-28` 现状(全部 `>=,<` 双界区间):

| 包 | pyproject spec | uv.lock 实锁 | 本 stage 目标 |
|---|---|---|---|
| langgraph | `>=1.0.0,<2.0.0` | 1.1.6 | **不动** |
| langgraph-checkpoint | `>=4.0.0,<5.0.0` | 4.1.1 | **不动**(已含 4.1.x) |
| langgraph-checkpoint-sqlite | `>=2.0.0,<3.0.0` | 2.0.10 | **抬上界** → `>=3.1.0,<4.0.0` |
| aiosqlite | (传递依赖,无上界) | 0.22.1 | **新增直接约束** `>=0.20,<1.0`(F-CS-01) |
| **sqlite-vec** | (3.x 新传递依赖) | 0.1.9 | **原生扩展,需纳入离线 bundle**(F-CS-04) |
| langchain / langchain-core | `>=1.0.0,<2.0.0` | 1.2.x | **不动** |

**F-CS-01(aiosqlite 约束)**:sqlite-saver 3.x 的 `AsyncSqliteSaver._ensure_connected` 经
`aiosqlite.Connection.is_alive`(0.22.1 无此属性)回退到私有 `conn._thread.is_alive()`。
`_thread` 是 aiosqlite 未公开私有属性,1.0 重构可能移除 → 击穿异步 checkpointer。显式约束
`aiosqlite<1.0` 锁定当前已知可行范围。

**F-CS-04(sqlite-vec 原生扩展)**:`langgraph-checkpoint-sqlite 3.1.0` 的 `requires_dist`
含 `sqlite-vec>=0.1.6`(原生 C 扩展,实测 `loadable_path()` 返回 `.so`)。离线/气隙部署
MUST 预下载 sqlite-vec wheel 并确认目标机 glibc/平台匹配。`requirements.md` 非功能「离线/气隙」
原写「无新增在线依赖」为误,**本 stage 实际新增 sqlite-vec 在线依赖**。回归测试
`test_sqlite_vec_importable_and_native_loadable` 固化导入+原生加载。

关键事实(读 PyPI `requires_dist` + 3.1.0 wheel 源码核实):
- `langgraph-checkpoint-sqlite 3.1.0` 要求 `langgraph-checkpoint>=4.1.0,<5.0.0` ——
  当前 pyproject 已允许(checkpoint 实锁 4.1.1),**resolver 抬 sqlite-saver 不会连带动
  checkpoint 主版本**。
- `langgraph 1.x` 要求 `langgraph-checkpoint>=2.1.0,<5.0.0`,与 4.1.x 兼容,langgraph
  主版本不动。
- `langchain 1.2.x` 在本仓库仅 2 处用到 `text_splitter`
  (`documents/markdown_parser.py:45`、`api/routers/documents.py:120`),稳定子模块,
  不受 checkpoint 升级影响。

**orchestrator.py:643-645 的注释("3.x sqlite saver requires checkpoint 2.x, project
pins 4.x")是过时信息**,与 PyPI 实际约束相反,删除 shim 时一并删该注释。

## 3. 3.x API 兼容性(从 3.1.0 wheel 源码核实)

- `SqliteSaver.__init__(conn: sqlite3.Connection, *, serde=None)` —— **签名不变**,
  `SqliteSaver(self._checkpoint_conn)`(L608)可保留,无需改 `from_conn_string`。
- `AsyncSqliteSaver.__init__(conn: aiosqlite.Connection, *, serde=None)` —— **签名不变**
  (L664 保留)。注意 3.x 构造时即 `asyncio.get_running_loop()`,需在 event loop 内;
  `astart()` 现状在 `async with lock` 内构造,已满足。
- `put/aput/put_writes`:3.x 全部改用 `self.serde.dumps_typed(checkpoint)` +
  `json.dumps(metadata)` / `json.loads(metadata)`,**无 `.dumps()`/`.loads()` 残留**。
- `setup()`:直接 `conn.executescript(...)`,**`setup()` 方法体不再调 `conn.is_alive()`**。
  **注意(F-CS-01)**:活跃度检查从 `setup()` 迁移到 `_ensure_connected`(经
  `_build_conn_started_check`),当 `aiosqlite.Connection` 无 `is_alive`(0.22.1 实测无)时
  回退到私有 `conn._thread.is_alive()`。`_thread` 是 aiosqlite 未公开私有属性,依赖它脆弱;
  故本 stage 显式约束 `aiosqlite<1.0` 锁定当前可行范围。
- → 现有 `is_alive` + `_dumps_shim` 两处 monkeypatch 整体可删(`_dumps_shim` 因 serde 已无
  dumps/loads;`is_alive` shim 因 aiosqlite 提供 `_thread` 回退得以移除,非因 3.x 完全不查活跃度)。

## 4. 改动清单(文件级)

| 文件 | 改动 | 回指 |
|---|---|---|
| `pyproject.toml:27` | `>=2.0.0,<3.0.0` → `>=3.1.0,<4.0.0`(用 `uv add`,禁手改) | REQ-CS-003 |
| `pyproject.toml` | 新增 `aiosqlite>=0.20,<1.0` 直接约束(F-CS-01) | REQ-CS-003 |
| `agent/harness/orchestrator.py` | 新增 `DEFAULT_CHECKPOINT_PATH`;新增 `_enable_strict_msgpack_deserialization()`(F-CS-06);`HarnessConfig.checkpoint_path` 用 `field(default_factory=...)`(F-CS-02) | REQ-CS-008/F-CS-06 |
| `agent/harness/orchestrator.py:641-663` | 删除整段兼容注释 + `is_alive` shim + `_dumps_shim` | REQ-CS-007 |
| `tests/conftest.py` `tmp_data_dir` | 增加 `monkeypatch.setattr("agent.harness.orchestrator.DEFAULT_CHECKPOINT_PATH", ...)` | REQ-CS-008 |
| `tests/unit/test_checkpoint_serde_compat.py` | 新建 regression test(19 用例:契约/saver/真实图/strict msgpack/sqlite-vec/Ollama E2E) | REQ-CS-005/006/007 + F-CS-03/04/06 |
| `tests/unit/test_retrieval_concurrency.py:14` | 修正悬空 docstring 引用 | — |

**不动**:`_setup_checkpointing()`(L595-612,本就无 shim,3.x 修复后自然能跑)、
graph 节点逻辑、shared_state 键、REST/CLI/env 契约。

## 5. 状态契约

无新增 `shared_state` 键(本 stage 不动 graph 节点)。`DEFAULT_CHECKPOINT_PATH` 是模块
级常量(非 shared_state),生产者 `orchestrator`、消费者 `HarnessConfig` 默认值 +
`tests/conftest.py` 重定向。

## 6. 降级策略(core/AGENTS.md §3)

`_setup_checkpointing()` 的 `except ImportError` → `MemorySaver()` fallback(L610-612)
**保持不变**。升级后 3.x 仍可能 `ImportError`(用户未装 sqlite-saver),该分支兜底。
**checkpointer 自身失败不属于热路径组件降级矩阵**(它是 graph 基础设施,非业务组件),
其语义是"不可用 → MemorySaver(丢失跨进程持久化但 graph 仍可跑)",已在现有代码覆盖,
本 stage 不改变该行为。

## 7. 测试矩阵

| 层 | 用例 | 文件 |
|---|---|---|
| 单元(红→绿) | 同步 `invoke()` 真实落盘 checkpoint,断言不抛 + 返回 dict | `tests/unit/test_checkpoint_serde_compat.py` |
| 单元(红→绿) | 异步 `astart()` + `ainvoke()`,断言不抛 + 返回正常 | 同上 |
| 单元 | `JsonPlusSerializer` 无 `dumps` 残留属性(确认 shim 已删净) | 同上 |
| 单元 | 密封性:checkpoint 落盘在 `tmp_path/data/` 而非真实 `./data/` | 同上 |
| 回归(F14 guard) | trace 隔离 contextvar 传播(checkpoint 主版本不动,应仍绿) | `tests/unit/test_trace_isolation.py` |
| 回归 | 同步 invoke 互斥锁 | `tests/unit/test_retrieval_concurrency.py` |
| E2E | `run_eval.py` 端到端:15/15 不再 ERROR,judge 可跑出真实数值 | 手动 + CI |

**确定性纪律**(§7):test 用 `HarnessConfig(checkpoint_path=str(tmp_path/...))` 显式
重定向(双重保险:既验证 REQ-CS-008 模块属性,又避免依赖 conftest);每用例
`harness.close()` / `await harness.aclose()` 释放连接,避免
`filterwarnings=error::ResourceWarning` fail。graph 用 fake/mock 避免依赖 Ollama/Milvus
(进程内 E2E 纪律)。

## 8. 回滚方案

- **依赖回滚**:`git revert` pyproject 改动 + `uv lock` 回退到 sqlite-saver 2.0.10。
- **数据**:`data/checkpoints.db` 是 2.0 格式。3.x 的 `setup()` 用
  `CREATE TABLE IF NOT EXISTS` 不改表结构,但 3.x 的 `writes` 表引入 `idx` 语义
  (`WRITES_IDX_MAP`)与 delta-channel 机制,与 2.0 行**混存会导致 writes 还原错序**
  (F-CS-07)。因此**升级时应清空/重建 `data/checkpoints.db` 而非续用旧库**(备份后删除)。
  跨大版本(2.x↔3.x)checkpoint 双向不可读 → **历史会话上下文不可续接,用户需重新发起会话**
  (功能降级,非数据腐蚀)。生产切换前 MUST 备份 `data/checkpoints.db`,并在变更通告告知用户
  会话重置。回滚到 2.x 后 3.x 写入的 checkpoint 反向也不可读。
- **代码回滚**:删除 `DEFAULT_CHECKPOINT_PATH` + 恢复 monkeypatch 即可(但不应回滚,
  因为 monkeypatch 是 bug 根源)。

## 9. 不变量影响

| 不变量 | 影响 |
|---|---|
| `agent/AGENTS.md §6` trace 隔离(依赖 langgraph 传播 contextvar) | 无:langgraph 主版本不动 |
| `core/AGENTS.md §3` 降级矩阵 | 无:checkpointer 的 ImportError→MemorySaver 分支不变 |
| `AGENTS.md §10` 持久化契约 | ✅ **改善**:新增 `DEFAULT_CHECKPOINT_PATH` 模块属性,补齐密封性缺口 |
| shared_state 键所有权 | 无:不动 graph 节点 |
| prompt 单一来源 | 无 |

## 10. 安全影响

| CVE | 描述 | 本 stage 是否闭合 |
|---|---|---|
| CVE-2025-64439 | `JsonPlusSerializer` json-mode 反序列化 RCE(CVSS 7.4);3.0 json allow-list + 移除不安全 json mode 修复 | ✅ json-mode 根因闭合(升到 4.1.1)+ msgpack 路径加固(strict,§11) |
| CVE-2025-67644 | checkpointer SQLi | ✅ 闭合(sqlite-saver 3.x 已修) |
| CVE-2026-27794 | 缓存层 RCE(checkpoint 4.0.0 修) | ✅ 闭合(升到 4.1.1) |

按 `AGENTS.md §8` 安全基线,本 stage 是安全修复 PR。CHANGELOG `[Unreleased]` 标
`[security]`。无需触碰 CORS/Admin/SSRF/PII/注入等其它基线。

## 11. 深度防御(msgpack strict)— 本 stage 已闭合(critic F-CS-06)

CVE-2025-64439 的**核心修复**(json-mode 反序列化 RCE)在 checkpoint 3.0.0 完成:json
allow-list + 移除不安全 json mode。升级到 4.1.1 已包含此修复。

但 `JsonPlusSerializer` 的 **msgpack** 反序列化路径默认是 **permissive**
(`allowed_msgpack_modules=True` = 任意类型实例化),除非设 `LANGGRAPH_STRICT_MSGPACK=true`。
checkpoint DB 落盘明文 BLOB,permissive msgpack 对任何能写 DB 者是 RCE 面。作为安全修复 PR,
**不能留此面开**,故本 stage 在 `orchestrator._enable_strict_msgpack_deserialization()`
强制 strict(`os.environ.setdefault` + 设 `_lg_msgpack.STRICT_MSGPACK_ENABLED=True`,幂等,绕过
env import-时序问题)。strict 只阻断**未注册自定义类型**;正常 graph state(dicts/scalars/messages)
是 `SAFE_MSGPACK_TYPES`,round-trip 不受影响(回归测试固化)。

回归测试(`TestStrictMsgpack`):① strict flag 已启用;② 默认 serializer 非 permissive;
③ strict 模式下正常 checkpoint round-trip 数据完整。

> 注:CVE-2025-64439 官方 CVSS 修订为 7.4(High,非早期流传的 9.8);本 stage 闭合其
> json-mode 根因 + 加固 msgpack 路径,纵深防御到位。
