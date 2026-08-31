# Critic 报告 — checkpoint-serde-compat(v2,整合后台独立 critic)

**评审对象**: `docs/specs/checkpoint-serde-compat/design.md`
**评审模式**: 完整 critic + STRIDE(安全基线)+ FMEA
**评审者**: 独立 critic(后台子 Agent + 父 Agent 交叉核实)
**结论**: **v1 发现 1 Critical(F-CS-06 归因待精确)+ 4 High**;**v2 已全部闭合**(见各 finding status)。后台 critic 的 F-CS-03/04/06 是父 Agent 同步评审的真实盲点,已诚实采纳。

---

## 摘要(v2 状态)

| ID | 严重性(v1) | v1→v2 处置 | v2 状态 |
|----|-----------|-----------|---------|
| F-CS-06 | Critical | msgpack permissive → 本 stage 强制 strict | **closed** |
| F-CS-01 | High | aiosqlite `_thread` 私有属性 → 加 `<1.0` 约束 | **closed** |
| F-CS-03 | High | regression 仅 saver API → 加非 gated 真实编译图测试 | **closed** |
| F-CS-04 | High | sqlite-vec 原生依赖漏记 → 补文档 + 气隙测试 | **closed** |
| F-CS-07 | High | 2.0↔3.x schema diff → 回滚改"重建而非续用" | **closed** |
| F-CS-02 | Medium | `str | None` 类型放宽 → 采纳 `default_factory` | **closed** |
| F-CS-05 | Medium | 回滚"无损"过强 → 改"会话重置" | **closed** |
| F-CS-08/09/10/11 | Low/Med | flaky/前置条件/措辞/tasks | accepted / 已记录 |

---

## praise(设计正确部分,防不公平苛责)

- `praise` design §1 根因链三环核实扎实:`SqliteSaver.put`(`__init__.py:387`)与
  `AsyncSqliteSaver.aput`(`aio.py:509`)确实全用 `dumps_typed`/`json.dumps`,**无
  `.dumps()`/`.loads()` 残留**。同步/异步 round-trip 实跑通过——**核心 BUG 确实被切断**
  (REQ-CS-001/002 功能性满足,baseline 0.000→0.755 印证)。
- `praise` §10 `DEFAULT_CHECKPOINT_PATH` 模块属性 + conftest 重定向补齐了
  AGENTS.md §10「落盘路径必须模块级属性」缺口,是正确的密封性修复。
- `praise` F-CS-03 提出的「非 gated 真实编译图」测试方案(StateGraph 单节点 + SqliteSaver,
  无 LLM)是父 Agent 未想到的更优解,已采纳。

---

## Findings(v2 全部 closed/accepted)

### F-CS-06 — Critical → closed(msgpack permissive RCE 面)
- **severity**: Critical(v1)/ closed(v2)
- **事实**: CVE-2025-64439 核心(json-mode RCE)3.0.0 已修(升 4.1.1 闭合);但 msgpack 路径
  默认 permissive(`allowed_msgpack_modules=True`),对能写 DB 者是 RCE 面。后台 critic 归因为
  「CVE 未闭合」**技术上需精确化**(CVE 是 json-mode,已闭合),但揭示的 msgpack 面**真实**。
- **v2 修复**: `orchestrator._enable_strict_msgpack_deserialization()` 强制 strict
  (`setdefault` env + 设 `_lg_msgpack.STRICT_MSGPACK_ENABLED=True`)。
- **verification**: `TestStrictMsgpack`(3 用例):flag 已启 / 默认 serializer 非 permissive /
  strict 下正常 round-trip 数据完整。
- **status**: **closed**

### F-CS-01 — High → closed(aiosqlite `_thread` 私有属性)
- **事实**: `AsyncSqliteSaver._ensure_connected` 经 `_build_conn_started_check` 回退
  `conn._thread.is_alive()`(`_thread` 私有)。design §3 原写"不再调 is_alive"部分不实。
- **v2 修复**: 约束 `aiosqlite>=0.20,<1.0` + design §3 精确化。
- **verification**: 版本约束在 pyproject;`test_async_saver_aput_aget_*` 实跑通过。
- **status**: **closed**

### F-CS-03 — High → closed(regression 仅 saver API,真实图路径未守护)
- **事实**: saver.put/get 绕过 graph→checkpointer 集成;真实图用例被 `requires_ollama` gate。
- **v2 修复**: `TestRealCompiledGraphCheckpoint`(StateGraph 单节点 + 真实 SqliteSaver,无 LLM)。
- **verification**: CI 默认跑,断言 graph.invoke 落盘 + get_tuple 读回。
- **status**: **closed**

### F-CS-04 — High → closed(sqlite-vec 原生依赖漏记)
- **事实**: sqlite-saver 3.1.0 新传递依赖 `sqlite-vec>=0.1.6`(原生 C 扩展),design/requirements
  原写"无新增在线依赖"为误。
- **v2 修复**: design §2 + requirements 补 sqlite-vec;`TestSqliteVecAirGap` 气隙测试。
- **status**: **closed**

### F-CS-07 — High → closed(2.0↔3.x schema diff + 回滚方案)
- **事实**: 3.x `writes` 表 `idx`/delta 机制与 2.0 混存会错序;design §8"无损"过强。
- **v2 修复**: design §8 改"重建而非续用旧库"+ 会话重置告知。
- **status**: **closed**

### F-CS-02 — Medium → closed(类型契约放宽)
- **事实**: `checkpoint_path: str | None` 放宽类型。后台 critic 推荐 `default_factory`,父 Agent
  defender 原错误认为其有时序风险,**实测后承认 critic 正确**(`SEALED? True`),采纳。
- **v2 修复**: 改 `field(default_factory=lambda: DEFAULT_CHECKPOINT_PATH)`,保持 `str` 类型。
- **verification**: `test_default_checkpoint_path_monkeypatch_taken_up` + `test_checkpoint_path_is_always_str_never_none`。
- **status**: **closed**(诚实承认 defender v1 判断错误)

### F-CS-05 — Medium → accepted(回滚无损性)
- design §8 措辞已从"无不可逆数据损失"改为"历史会话重置(功能降级,非数据腐蚀)"。
- **status**: **closed**

### F-CS-08/09/10/11 — Low/Medium → accepted
- F-CS-08(gated e2e 触全局单例):accepted,gated 用例 skip 时不污染;F-CS-09(astart 前置
  register_defaults):accepted,生产单例 `get_agent_harness` 已 register;F-CS-10(checkpointer
  分类措辞):design §6 已记录;F-CS-11(安全验收 tasks):tracking 已列安全测试。

---

## STRIDE(v2)
无 Critical/High 残留:Tampering/Elevation 的 msgpack 面已 F-CS-06 闭合(strict);其余 N/A。

## 合并门禁
**v2 全部 Critical/High closed**,门禁通过。
