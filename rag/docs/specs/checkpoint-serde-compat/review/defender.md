# Defender 报告 — checkpoint-serde-compat(v2)

**评审对象**: `review/critic.md` v2
**裁决基准**: defender.md 5 步决策树 + 实测证据
**说明**: 本报告对后台独立 critic 的 findings 逐一裁决。**诚实原则**:对 F-CS-02,
defender v1 曾错误认为 `default_factory` 有时序风险,**实测后承认 critic 正确并采纳**(反护短)。

## 裁决表

| 发现 ID | 严重性 | 决策 | 理由(实测证据) | design 修订 |
|---------|--------|------|----------------|-------------|
| F-CS-06 | Critical | **accepted(已修)** | msgpack permissive 真实 RCE 面。CVE-2025-64439 核心是 json-mode(已闭合),但 msgpack 默认 permissive 是独立面。安全 PR 不应留此面开。成本极低(`_enable_strict_msgpack`)。 | §11 升级为本 stage 必做 |
| F-CS-01 | High | **accepted(已修)** | `_thread` 私有属性依赖属实。实测 aiosqlite 0.22.1 类层无 `is_alive`/`_thread`。加 `aiosqlite<1.0` 约束是最小成本闭合。 | §3 精确化 + §2 加约束行 |
| F-CS-03 | High | **accepted(已修)** | saver API 测试确实绕过 graph 集成。critic 的「StateGraph 单节点 + SqliteSaver 无 LLM」方案是更优解,父 Agent 未想到。 | §7 测试矩阵加非 gated 真实图 |
| F-CS-04 | High | **accepted(已修)** | sqlite-vec 原生依赖漏记属实(`requires_dist` 实测含 `sqlite-vec>=0.1.6`)。requirements 原写"无新增在线依赖"为误。 | §2 + requirements 补 |
| F-CS-07 | High | **accepted(已修)** | schema diff 风险属实(3.x writes.idx/delta)。回滚"无损"措辞过强。 | §8 改"重建而非续用" |
| F-CS-02 | Medium | **accepted(采纳 critic,推翻 defender v1)** | **诚实更正**:defender v1 称 `default_factory` 有"早构造实例缓存"时序风险,**实测 `SEALED? True` 证明错误**——`default_factory` 每次实例化重读模块属性,无缓存,且保持 `str` 类型。critic 更优,采纳。 | §4 改 `default_factory` |
| F-CS-05 | Medium | **accepted** | 回滚无损性论断过强,已改"会话重置"。 | §8 |
| F-CS-08/09/10/11 | Low/Med | **accepted** | flaky/前置/措辞/tasks,已记录或现状合理。 | §6/§7 |

## 逐条决策树关键步骤

### F-CS-06(Critical)
1. 事实为真?✅ `_allowed_msgpack_modules=True`(实测)。
2. 可触发?✅ 攻击者写 DB → msgpack ext 任意类型实例化。
3. 成本 vs 影响?Critical 安全 + 低成本(`setdefault` + 设模块属性)→ **必须接受**。
4. CVE 归因精确化:json-mode(CVE 核心)已闭合;msgpack 是独立面。但安全 PR 不应留独立面开。

### F-CS-02(Medium,诚实更正)
defender v1 决策树:
1. 事实为真?✅ `str | None` 放宽类型。
2. 修复 `default_factory` 有时序风险?→ **实测反证**:`default_factory=lambda: orch.DEFAULT_CHECKPOINT_PATH` 在 monkeypatch 后新实例读新值(`SEALED? True`),**无缓存,无时序问题**。
3. defender v1 的"早构造实例缓存"担忧是错误推理(dataclass `default_factory` 每次实例化都调 lambda)。
→ **采纳 critic,推翻 defender v1**。这是反护短的体现。

## 净裁决
**所有 Critical/High closed**,Medium accepted。合并门禁通过。

## 实测证据汇总
- F-CS-06:`STRICT_MSGPACK_ENABLED=True` + `_allowed_msgpack_modules != True` + strict round-trip 数据完整。
- F-CS-02:`default_factory` monkeypatch `SEALED? True` + `isinstance(checkpoint_path, str)`。
- F-CS-03:真实编译图 `graph.invoke({'count':1})` → `{'count':2}` + checkpoint 落盘。
- F-CS-04:`sqlite_vec.loadable_path()` 返回 `.so`。
- 整体:19/19 regression + baseline 0.000→0.755。
