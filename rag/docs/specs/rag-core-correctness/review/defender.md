# Defender 报告 — RAG Core Correctness

**评审对象**: `review/critic.md`
**评审日期**: 2026-07-15

## 裁决表

| 发现 | 决策 | 设计修订 |
|---|---|---|
| F-01 | accepted | provider-aware effective defaults |
| F-02 | accepted | model fingerprint + dimension + sparse 三重门禁与新 collection 迁移 |
| F-03 | accepted | PreparedEvidence + generation_evidence kept-set |
| F-04 | accepted | 所有 evidence→LLM 路径共享安全 renderer |
| F-05 | accepted | BEGIN IMMEDIATE、锁内重检、逐条迁移与失败关闭连接 |
| F-06 | accepted | v1 backup、停服务恢复与前滚策略 |
| F-07 | accepted | 有界递归 sanitizer 与局部降级 |
| F-08 | accepted | 字段级 score 语义与 None 降级 |
| F-09 | accepted | 共享 pure helper + sync/async 测试矩阵 |
| F-10 | accepted | Fast 三入口共享 packer |
| F-11 | accepted | canonical fingerprint schema v1 |

## 关键论证

- Markdown heading stack 是闭合当前父链错误的最小方案；完整 CommonMark AST 另列后续。
- 新 namespaced `retrieval_evidence`/`generation_evidence` 分离原始与 kept 所有权，符合 shallow reducer 整键覆盖。
- relation 逻辑 ID 保持概念级稳定，source 作为复合 PK 第二列即可同时满足跨源图遍历与持久化隔离。
- sigmoid 只作为 raw logit 的稳定数值映射，不宣称统计校准；temperature/isotonic 留待有标注数据后实施。

## 有限边界

- fenced code/setext Markdown 与完整 AST 不在本阶段。
- adaptive router、动态 Top-K/RRF、community/global GraphRAG 不在本阶段。
- Graph v2 观察期写入若回滚到 v1 备份会丢失；不能接受时只允许前滚修复。

---

## v4 Final Review — 2026-07-16

**评审对象**：F-12～F-18、implementation `440092b`、当前规格与验证日志
**评审方式**：独立上下文，逐项执行“事实→可触发→成本/影响→范围→替代”决策树

### Decision table

| Finding | Gate severity | Decision | Evidence | Status |
|---|---:|---|---|---|
| F-12 | Critical | accepted | request reset + same-thread/four-entry tests | closed at `440092b` |
| F-13 | Critical | accepted | actual source + `is_bge_m3` + opaque-cache red→green | closed at `440092b` |
| F-14 | Critical | accepted | tracked fail-closed baselines + two real gates | closed at `440092b` |
| F-15 | High | accepted | closed-interval formatter + Playwright | closed at `440092b` |
| F-16 | High | accepted | consumer normalization + strict saver | closed at `440092b` |
| F-17 | High | accepted | review/tasks/tracking must match current facts | closed at `3ea045d` |
| F-18 | Medium | defended-with-alternative | version rollback + compatibility drill | closed |

### F-12 — Request-state isolation

原 finding 事实成立且可触发：浅合并 reducer 会保留未覆盖键。更换 thread 会破坏会话连续性，删除 reducer
会破坏架构不变量，均不等价。`_build_request_shared_state` 统一四入口、屏蔽 producer-owned caller 注入并保留
显式空 history，是影响最小的完整修复。永久回归为
`tests/unit/test_shared_state.py::TestRequestBoundarySharedState`。

**Decision**: accepted；implementation `440092b` 后 closed。

### F-13 — Embedding identity and model family

原 finding 与终审新增的 opaque-cache 反向场景均成立。仅修 registry 或仅修 loader 都不能阻断共因失效。
当前 `EmbeddingSettings` 分离 configured model family、actual `model_source`、dimension 与 sparse capability；loader
按 `is_bge_m3` 分派，Milvus/registry 使用 actual source。证据包括 opaque-cache `1 failed → 1 passed`、配置
`36 passed`、dispatch `2 passed` 与两份 post-fix real benchmark gate PASS。

**Decision**: accepted；implementation `440092b` 后 closed。

### F-14 — Benchmark gate

缺基线自动 seed 会使 fresh runner 全零质量也放行，runtime baseline 不是等价替代。tracked baseline 绑定 schema、
dataset/corpus digest、case/top-k/dedup/repeats 与 embedding identity，并将 update 与 gate 设为互斥，是可审计的
最小方案。CMRC2018 与 HotpotQA fresh 三轮 gate 均 PASS。

**Decision**: accepted；implementation `440092b` 后 closed。

### F-15 — UI score boundary

`1.0` 合法且旧开放区间可稳定触发错误。闭区间 formatter 成本低、没有等价替代；`null` 隐藏与 `0.0` 保留
同时满足“不可用不等于零”不变量。Playwright `19 passed`，截图已核验。

**Decision**: accepted；implementation `440092b` 后 closed。

### F-16 — strict-msgpack consumer boundary

依赖 serializer 最终抛错不是安全降级。producer/consumer 共用递归 allowlist、非法 metadata 局部清理、结构非法
回退 legacy message，以及 harness 在 checkpoint 前屏蔽 caller evidence，闭合了实际触发路径。永久回归覆盖
object/Path/cycle/NaN/越界整数与 sync/async saver。

**Decision**: accepted；implementation `440092b` 后 closed。

### F-17 — Review evidence drift

实现通过不等于工程门禁完成；旧 review/tracking 会让 Critical/High 缺 commit、verification、regression 四列。
不存在等价替代，必须归档终审、刷新 tasks 并写入真实 SHA。

**Decision**: accepted；review archive `3ea045d` 后 closed。

### F-18 — Rollback without a feature flag

原文档对 feature flag 的陈述不实，但新增运行时开关会扩大热路径控制面。更简单的等价方案是保留 legacy
`ToolMessage`/开放 shared-state 契约，并以版本回退处理异常发布。该替代现已通过实际演练：`440092b` 写入含
新键 checkpoint，`origin/main@45d68f0` 成功读取并继续 invoke。

**Decision**: defended-with-alternative；closed。

### Final verification

- Backend: `917 passed, 6 skipped, 7 warnings`
- Ruff / format / diff check / import: passed
- Web build: passed
- Playwright: `19 passed`; sessions repeat: `12 passed`
- CMRC2018: hit worst `1.000`, precision worst `0.250`, recall worst `1.000`, gate PASS
- HotpotQA: hit worst `1.000`, precision worst `0.458`, recall worst `0.917`, gate PASS
- Rollback drill: `CURRENT_WRITE_OK` + `ORIGIN_MAIN_READ_AND_CONTINUE_OK`

### Limited boundaries

- `answer_overlap` 仅 advisory，不作为质量门禁。
- baseline 不绑定本地绝对路径，但绑定 model/provider/dimension/sparse。
- Graph v2 回滚到 v1 backup 会丢失观察期新增 graph 写入。
- 既有依赖弃用与 SQLite `ResourceWarning` 未造成失败，仍是后续生命周期技术债。

**Push Gate**：F-12～F-18 已满足运行时与工程门禁，允许 push。
