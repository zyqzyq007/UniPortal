# Critic 报告 — RAG Core Correctness

**评审对象**: `docs/specs/rag-core-correctness/{requirements,design,tasks}.md` v1-v3
**评审模式**: 完整 critic + FMEA + STRIDE + 数据迁移/回滚
**评审日期**: 2026-07-15

## 摘要

- 首轮：Critical 3、High 7、Medium 1；结论为必须修订后编码。
- v2：关闭 9/11，F-02 与 F-04 保持 Critical open。
- v3：最终定向复核确认 F-02/F-04 closed，无剩余 Critical/High 设计 finding，可进入红测试。

## Findings

### F-01 — API provider 会继承无效的本地模型默认值
- **severity**: Critical
- **location**: `utils/env_utils.py` / `models/embedding_models.py`
- **symptom**: auto 在无 local deps 时解析为 API，却把 BGE-M3 名称发送给 DashScope。
- **impact**: API-only 默认检索不可用。
- **root_cause**: local/API 默认未按 effective provider 分离。
- **recommendation**: provider-aware resolver；local=BGE-M3/1024，API=v3/512，显式 env 优先。
- **verification**: local/API/auto 子进程测试与 DashScope payload 断言。
- **status**: closed-in-design-v2

### F-02 — embedding-space 不兼容没有完整迁移门禁
- **severity**: Critical
- **location**: `documents/milvus_db.py` / `documents/embedding_registry.py`
- **symptom**: 同维不同模型或 512→1024 时可能继续查询旧 collection。
- **impact**: 排序静默失真或多检索腿共同为空。
- **root_cause**: schema compatibility 被误当作 embedding-space compatibility。
- **recommendation**: effective model fingerprint + dimension + sparse capability 任一不匹配均阻断；按 effective target 建新 collection。
- **verification**: BGE-small/512→DashScope-v3/512 阻断；local/API 两类目标迁移。
- **status**: closed-in-design-v3

### F-03 — kept evidence 未成为所有消费者的事实来源
- **severity**: High
- **location**: `agent/skills/generate/skill.py` / `api/routers/chat.py`
- **symptom**: budget 丢弃的文档仍进入 grounding、confidence 或 REST sources。
- **impact**: 引用与模型实际 prompt 不一致。
- **root_cause**: 缺少原子 PreparedEvidence 数据流。
- **recommendation**: generation_evidence kept-set 供生成、grounding、置信度与 API 共用。
- **verification**: 超预算同步/异步/API 一致性测试。
- **status**: closed-in-design-v2

### F-04 — evidence prompt 定界未覆盖全部 LLM 消费者
- **severity**: Critical
- **location**: Generate、Fast、GradeSkill、per-doc grader prompts
- **symptom**: 恶意文档可操纵 relevance grade 或生成。
- **impact**: 间接 prompt injection 可绕过 rewrite/refusal。
- **root_cause**: 误认为既有 generate prompt 已有定界。
- **recommendation**: 共享不可逃逸 renderer + data-only 指令覆盖所有 evidence→LLM 路径。
- **verification**: generate/binary grade/per-doc grade sync+async golden。
- **status**: closed-in-design-v3

### F-05 — Graph SQLite migration 缺数据库级互斥
- **severity**: High
- **location**: `documents/graph_store.py`
- **symptom**: 多 worker 可并发判断并迁移同一 v1 DB。
- **impact**: 半迁移或持续 degraded。
- **root_cause**: 仅进程内 RLock，未规定 SQLite write lock 与 schema recheck。
- **recommendation**: BEGIN IMMEDIATE、锁内重检、逐条 DDL、rollback/reopen。
- **verification**: 双 connection 并发与阶段注错测试。
- **status**: closed-in-design-v2

### F-06 — Graph rollback 不可执行
- **severity**: High
- **location**: graph migration rollback
- **symptom**: v2 写入后旧二进制无法直接读取，单列 PK 恢复会冲突。
- **impact**: 发布回滚失败或关系数据丢失。
- **root_cause**: 关闭 GraphRAG 与恢复 schema 被混淆。
- **recommendation**: 迁移前 SQLite backup；回滚停服务并恢复 v1，声明观察期写入丢失。
- **verification**: v1→v2→写入→v1 恢复演练。
- **status**: closed-in-design-v2

### F-07 — evidence sanitizer 未定义
- **severity**: High
- **location**: structured evidence/checkpoint
- **symptom**: numpy、Path、NaN、循环或深层 metadata 可打断 strict checkpoint。
- **impact**: 整批 evidence 回退或 checkpoint 失败。
- **root_cause**: 只有允许类型，没有局部失败策略与限额。
- **recommendation**: 递归 allowlist、有限值、深度/长度限额、大向量丢弃。
- **verification**: sync/async strict checkpoint 边界测试。
- **status**: closed-in-design-v2

### F-08 — 分数字段标尺冲突
- **severity**: High
- **location**: `agent/skills/grade/per_doc_scoring.py`
- **symptom**: raw logit、probability、RRF score 被当作相同 `[0,1]` 信号。
- **impact**: 排序、拒答和置信度失真。
- **root_cause**: 历史字段语义未区分，不可用被伪造为 0.5/0。
- **recommendation**: raw-only sigmoid、prob 原样校验、未知/RRF 不参与概率融合、None 降级。
- **verification**: 极值、NaN、非法 JSON、全 None sync/async golden。
- **status**: closed-in-design-v2

### F-09 — sync/async 对称性未锁定
- **severity**: High
- **location**: Retrieve/Generate sync+async
- **symptom**: 生产 async 可能仍使用旧消息 grounding。
- **impact**: eval 与生产行为分叉。
- **root_cause**: 两套重复实现且原测试矩阵未逐面验收。
- **recommendation**: 共用 pure helper，分别覆盖 execute/aexecute/saver/astream。
- **verification**: 同 fixture 对拍 state/context/sources/scores。
- **status**: closed-in-design-v2

### F-10 — Fast mode 截半证据并返回未用来源
- **severity**: High
- **location**: `core/fast_mode.py`
- **symptom**: 字符级截断 prompt，同时返回全部 document sources。
- **impact**: 引用与模型证据不一致。
- **root_cause**: Fast 绕过 RetrieveSkill/GenerateSkill 数据流。
- **recommendation**: 三个 fast 入口复用 evidence packer。
- **verification**: sync/async/stream 超预算对拍。
- **status**: closed-in-design-v2

### F-11 — 配置指纹缺规范化算法
- **severity**: Medium
- **location**: config fingerprint
- **symptom**: 相同 effective config 可能因字面写法产生不同 hash。
- **impact**: 运行配置追踪出现假漂移。
- **root_cause**: 仅选定 SHA-1，未定义 canonical payload。
- **recommendation**: schema_version + effective values + sorted compact JSON；排除 URI/path/secret。
- **verification**: 等价配置同 hash，关键字段变化异 hash。
- **status**: closed-in-design-v2

## FMEA / STRIDE 结论

- 共因：embedding 默认切换同时影响 dense schema、sparse capability 与 graph BLOB，必须整体迁移。
- Prompt injection：上传者可经 filename/title/content 篡改 grade/generate，F-04 为安全门禁。
- Graph DDL：多进程迁移与备份/回滚必须独立验证。

---

## v4 Final Review — 2026-07-16

**评审对象**：当前实现提交 `440092b` 与 `docs/specs/rag-core-correctness/` v4
**评审模式**：完整 critic + FMEA + STRIDE + 回滚门禁
**独立复验**：定向 `150 passed, 2 skipped`；完整矩阵 `917 passed, 6 skipped`

### Summary

| Finding | Severity | Final status |
|---|---:|---|
| F-12 请求级 `shared_state` 隔离 | High | closed by `440092b` |
| F-13 embedding 实际身份与加载族 | Critical | closed by `440092b` |
| F-14 benchmark baseline fail-closed | High | closed by `440092b` |
| F-15 UI `1.0` 分数边界 | Medium | closed by `440092b` |
| F-16 evidence metadata wire safety | High | closed by `440092b` |
| F-17 review/tracking 未同步 | High | closed by `3ea045d` |
| F-18 旧版本 checkpoint 回滚演练 | Medium | closed by compatibility drill |

### F-12 — checkpoint 请求态跨轮串扰

- **id**: F-12
- **severity**: High
- **location**: `agent/harness/orchestrator.py` 的 `_build_request_shared_state` 与四个 graph 入口；`tests/unit/test_shared_state.py::TestRequestBoundarySharedState`。
- **symptom**: 浅合并 reducer 下，未显式覆盖的旧 evidence、sources、memory、history 与分数会留到下一请求。
- **impact**: 本轮提前结束或 generate 前失败时可能消费上一轮来源和置信度。
- **root_cause**: 旧入口只叠加本轮增量，没有统一请求级中性态。
- **recommendation**: 四入口统一构造完整中性态；caller 不得覆盖 producer-owned 键；`history is not None` 保留显式空列表语义。
- **verification**: same-thread 真实 SQLite 两轮、四入口对称、caller producer-key 屏蔽测试；全矩阵 `917 passed`。
- **status**: closed，implementation `440092b`。

### F-13 — embedding identity、实际加载源与 adapter family 漂移

- **id**: F-13
- **severity**: Critical
- **location**: `utils/env_utils.py::EmbeddingSettings`、`models/embedding_models.py::_get_local_embeddings`、`documents/milvus_db.py`。
- **symptom**: custom model 可能继承 BGE-M3 path/sparse；BGE-M3 位于不含模型名的缓存目录时也曾误走 dense-only adapter。
- **impact**: registry、Milvus sparse schema 与实际向量模型能力静默分叉，检索空间整体失真。
- **root_cause**: 将模型家族判定与加载路径字符串混为一个字段。
- **recommendation**: `model_source` 只定位实际权重，独立 `is_bge_m3` capability 决定 adapter；custom dimension 必填，非 BGE-M3 禁用 native sparse。
- **verification**: `/tmp/rcc-f13-opaque-cache-red.log` `1 failed` → green `1 passed`；配置 `36 passed`、dispatch `2 passed`；CMRC/Hotpot post-fix gate PASS。
- **status**: closed，implementation `440092b`。

### F-14 — benchmark regression gate fail-open

- **id**: F-14
- **severity**: High
- **location**: `scripts/run_benchmark.py` baseline schema/gate、`.github/workflows/benchmark-regression.yml`、`data/benchmark/baselines/`。
- **symptom**: 缺失、损坏或配置错配的 runtime baseline 曾可自动播种并放行。
- **impact**: fresh runner 上即使召回质量归零也可能通过。
- **root_cause**: runtime 结果缓存被误当作版本化质量契约。
- **recommendation**: tracked baseline 绑定 schema、dataset/corpus digest、运行参数与 embedding identity；缺失/错配 fail closed；仅显式原子 update 可写。
- **verification**: 缺失/坏 JSON/非有限/配置错配单测；CMRC2018 与 HotpotQA 各三轮 fresh gate PASS。
- **status**: closed，implementation `440092b`。

### F-15 — `score == 1.0` 未显示为 `100.0%`

- **id**: F-15
- **severity**: Medium
- **location**: `web/src/views/ChatView.vue::formatSourceScore`；`tests/e2e_ui/chat.spec.ts`。
- **symptom**: 旧开放区间使 `1.0` 显示为 legacy fixed decimal。
- **impact**: 满相关度与同一面板的百分比标尺不一致。
- **root_cause**: formatter 未按 `[0,1]` 闭区间处理。
- **recommendation**: nullable score 只在 `!= null` 时渲染；闭区间统一百分比；legacy `>1` 保持固定小数。
- **verification**: UI 红测后完整 Playwright `19 passed`；截图同屏含 `100.0% / 92.0% / 0.0%` 且 null 隐藏。
- **status**: closed，implementation `440092b`。

### F-16 — metadata 绕过 strict-msgpack 契约

- **id**: F-16
- **severity**: High
- **location**: `core/retrieval/evidence.py` sanitizer/normalizer；Generate consumer；harness 请求边界。
- **symptom**: object、Path、循环、越界整数或非法嵌套曾可通过浅层 shape 检查并在 checkpoint 抛错。
- **impact**: generate/checkpoint 热路径向外失败，而不是局部降级。
- **root_cause**: producer sanitizer 与 consumer validator 强度不一致。
- **recommendation**: producer/consumer 共用有界递归 allowlist，局部丢弃并传播 degraded；caller producer-owned evidence 在 checkpoint 前屏蔽。
- **verification**: object/Path/cycle/NaN/正负越界整数、sync/async strict saver round-trip 与 legacy fallback 测试。
- **status**: closed，implementation `440092b`。

### F-17 — Spec/review/tracking 与实现事实不一致

- **id**: F-17
- **severity**: High
- **location**: `tasks.md` 与 `review/{critic,defender,tracking}.md`。
- **symptom**: v4 实现完成后，正式评审与 Verification Record 仍停留在 F-01～F-11 和旧测试数。
- **impact**: Critical/High finding 没有 commit、验证、永久回归四列证据，违反合并门禁。
- **root_cause**: 实现与验证先于评审归档更新。
- **recommendation**: 归档本终审与 Defender 裁决，使用真实 implementation SHA 更新 tracking，再独立提交文档闭环。
- **verification**: tracking 覆盖 F-12～F-18，且 Critical/High 四列完整。
- **status**: closed；review archive `3ea045d`，tracking 已填入 implementation/verification/regression 四列。

### F-18 — rollback 曾声明不存在的 feature flag

- **id**: F-18
- **severity**: Medium
- **location**: `design.md` Rollback。
- **symptom**: 旧设计曾声称可用 feature flag 停用 evidence，但实现没有该控制面。
- **impact**: 运维可能在发布异常时依赖不可执行的回滚步骤。
- **root_cause**: 回滚文档描述了未实现机制。
- **recommendation**: 使用版本回退 + checkpoint/legacy message 前后兼容，不新增运行时 flag；回退前执行旧版本读取演练。
- **verification**: `440092b` 写入含新 evidence 与 legacy `ToolMessage` 的 checkpoint；`origin/main@45d68f0` 成功读取并继续 invoke，输出 `ORIGIN_MAIN_READ_AND_CONTINUE_OK`。
- **status**: closed，采用 Defender 的等价替代并完成实际 drill。

### FMEA

| Component | Failure mode | S | O | D | RPN | Control |
|---|---|---:|---:|---:|---:|---|
| Request scratchpad | stale evidence 跨轮 | 4 | 3 | 4 | 48 | 四入口统一重置 |
| Embedding identity | 错误空间/adapter family | 5 | 3 | 4 | 60 | `is_bge_m3` + actual source + compatibility gate |
| Benchmark gate | baseline 缺失/错配放行 | 3 | 3 | 4 | 36 | schema/digest/config fail-closed |
| UI score | 0/1 边界误显示 | 2 | 4 | 2 | 16 | 闭区间 formatter + Playwright |
| Evidence metadata | strict-msgpack failure | 4 | 3 | 3 | 36 | recursive normalization + local degradation |
| Rollback | old code cannot read checkpoint | 3 | 2 | 3 | 18 | actual old-version drill |

### STRIDE

| Category | Result |
|---|---|
| Spoofing | 未改变身份认证面。 |
| Tampering | caller producer-owned evidence 注入已在 harness 边界阻断。 |
| Repudiation | baseline digest、fingerprint 与 tracking 提升审计性。 |
| Information Disclosure | sanitizer 删除 Path 等对象；指纹不含 secret、URI、绝对路径。 |
| DoS | 非法 metadata 局部降级，embedding 不兼容 fail fast/degraded。 |
| Elevation | 未改变 Admin 权限边界。 |
| OWASP LLM | evidence 定界和 data-only 指令覆盖 generate/grade。 |

**Push Gate**：运行时代码无新增阻断；F-12～F-18 均已闭环，允许 push。
