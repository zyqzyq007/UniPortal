# Defender 报告 — retrieval-benchmark-expansion

**评审对象**: `docs/specs/retrieval-benchmark-expansion/review/critic.md`
**复核版本**: `requirements.md` / `design.md` v2 / `tasks.md`
**评审日期**: 2026-07-16

## 结论

critic 对 v1 的 F-01～F-10 事实陈述均成立，没有可用 `rejected` 反证。v2 已在设计层关闭 F-01、F-06、
F-09、F-10；F-02、F-03、F-04、F-05、F-07、F-08 已接受方向但仍有可达缺口，必须先补 v2.1 再编码。
这不是要求先实现才能证明，而是当前设计尚未定义足以实现/测试的最后一段契约。

## 裁决表

| 发现 ID | 严重性 | 决策 | v2 闭环状态 | 理由（证据 / 替代方案） | design 修订 |
|---|---|---|---|---|---|
| F-01 | Critical | accepted | design-closed | v2 §2 将 policy 扩展到 planner/representation/retry/fallback/post-process，§3 给出完整 baseline，§9 有故障注入 | v2 §2、§3、§8、§9 |
| F-02 | Critical | accepted | **open** | local-only child 已接受，但 `utils/env_utils.py:11-14` 会从仓库 `.env` 重新载入被清除的 key/URL | 需 v2.1 §4.2 |
| F-03 | Critical | accepted | **open** | graded qrels/evaluator 已接受，但未定义如何从生产 `final_k` 获取 Recall@100 所需 top-100 run | 需 v2.1 §5.4 |
| F-04 | High | accepted | **open** | identity 已完整；但在线程/async task 内直接更新 ContextVar 会丢失或竞态，聚合所有权未定义 | 需 v2.1 §2.2 |
| F-05 | High | accepted | **open** | balanced schedule/effective attestation 已接受；仍受 `.env` 注入，且 REQ-RBE-003 的 forward/reverse 与 cyclic Latin 语义不一致 | 需 v2.1 §4.1-4.2 |
| F-06 | High | accepted | design-closed | v2 §6.1 已定义工作量、磁盘、输出和 wall-time 上限及进程组回收；实现必须给非空安全默认值 | v2 §6.1、§8、§9 |
| F-07 | High | accepted | **open** | generation/pointer/checkpoint 方向正确，但未要求 rename/replace 后 fsync 父目录，断电持久性仍未闭合 | 需 v2.1 §4.4、§5.3 |
| F-08 | High | accepted | **open** | 阶段指标已补齐；但当前统一摄入会让 BM25-only 仍承担 dense Milvus embedding/index 成本，资源对比会失真 | 需 v2.1 §3、§6.2 |
| F-09 | High | accepted | design-closed | v2 §9 与 tasks T1～T3 已按 finding 映射 fault injection、documents-route E2E、真实 child 测试 | v2 §9；tasks T1.1～T3.4 |
| F-10 | High | accepted | design-closed | query hash、hash-suffixed slug、source fingerprint、conversion summary 与 iterator shuffle 测试均已定义 | v2 §5.2-5.3、§7、§9 |

## 逐条论证

### F-01 — 通道关闭契约

- **步骤 1 核验**: critic 事实为真。现代码同步外层异常会无条件 dense fallback
  (`core/retrieval/hybrid_retriever.py:563-570`)，MMR/representation/planner 也不是由 dense/sparse 开关统一
  控制。
- **步骤 2 触发**: 可通过 RRF/reranker/MMR 异常或 BM25-only 默认 MMR 稳定触发，不是理论路径。
- **步骤 3 成本**: 影响 Critical；统一 policy 与 fault-injection 测试成本中等，必须修。
- **步骤 4 范围**: 属本功能核心范围，直接决定 baseline 是否真实。
- **步骤 5 替代**: 仅在 matrix wrapper 跳过 dense 不等价，因为生产 fallback/planner 仍可复活通道。
- **决策**: `accepted`。
- **v2 核验**: `design.md:20-37` 已将 `ActiveChannelPolicy` 定义为所有正常/异常路径唯一事实来源；
  `design.md:61-75` 给出 8 个完整 stage 配置；`design.md:228-245` 明确异常、filter、query-forward 和 E2E。
  在设计层关闭，最终状态仍需实现和永久测试证据。

### F-02 — 离线与私域不外发

- **步骤 1 核验**: critic 事实为真；现 paired runner 使用 `os.environ.copy()`，`auto` provider 可走 API。
- **步骤 2 触发**: v2 仍存在一个未覆盖的可达入口：`utils/env_utils.py:11-14` 在 child import 时执行
  `load_dotenv(override=False)`。最小 child env 删除 key 后，仓库 `.env` 会把这些 key/base URL 重新填回。
- **步骤 3 成本**: 信息泄露影响 Critical；修复成本低。
- **步骤 4 范围**: 属 benchmark 安全边界，不是历史范围外问题。
- **步骤 5 替代**: 仅强制 `EMBEDDING_PROVIDER=local` 能阻止当前 embedding API 路径，但不能证明 child env
  无 secret，也不能约束未来导入路径；不等价。
- **决策**: `accepted`，v2 尚未完全关闭。
- **必须修订**: v2.1 §4.2 明确 child 强制 `PYTHON_DOTENV_DISABLED=1`，并在 canary 测试中同时放置宿主
  env 与仓库 `.env` key/remote URL；effective attestation 必须记录 `dotenv_disabled=true`、
  `network_mode=offline`，但不得记录 secret。active 本地组件逐项 preflight，disabled reranker 不应被误要求。

### F-03 — 公开协议可比性

- **步骤 1 核验**: critic 事实为真；现 harness 使用 binary ids 和任意 top-k。
- **步骤 2 触发**: v2 已引入 graded-qrel evaluator，但 `design.md:161-172` 只规定指标，没有定义检索深度。
  生产/harness `final_k=4/5` 的 ranked run 最多只能计算 Recall@4/5，不能计算 Recall@100。
- **步骤 3 成本**: 错误公开声明影响 Critical；增加独立 public-quality protocol 成本中等。
- **步骤 4 范围**: 属公开 baseline 的核心事实契约。
- **步骤 5 替代**: 用 evaluator 对不足 100 条的 run 计算 `Recall@100` 在数学上可执行，但不具官方协议等价性，
  因为检索器从未获准返回第 6～100 名；不能接受。
- **决策**: `accepted`，v2 尚未完全关闭。
- **必须修订**: 明确分离两类 run：
  1. `public_quality` 以 registry 的 `evaluation_depth>=max_cutoff`（当前至少 100）运行，并保证
     candidate/rerank/output depth 足够，输出稳定 `(qid, docid, score)`；
  2. `production_performance` 保持实际 final/candidate budgets 测量延迟与资源。
  两类指标不得混为同一 Pareto 观测。`official_comparable` gate 还必须检查实际 retrieved depth。Acceptance
  Criteria 应包含 v2 的 `full-local` 类，而不只列 official/sampled/synthetic。

### F-04 — Cache Identity 与 Diagnostics

- **步骤 1 核验**: critic 事实为真；v1 identity 和 docs-only diagnostics 不足。
- **步骤 2 触发**: v2 identity 字段已完整，但 `design.md:41-51` 仅说模块级 ContextVar 保存 execution info。
  当前 sync parallel 使用 `ThreadPoolExecutor.submit` (`hybrid_retriever.py:1203-1239`)，worker 的 ContextVar
  更新不会自动汇回 parent；async task 继承 context 后直接修改可变对象又可能形成共享竞态。
- **步骤 3 成本**: 影响 High；改为显式 immutable typed result 的成本中等。
- **步骤 4 范围**: 属本功能 diagnostics/cache 正确性范围。
- **步骤 5 替代**: v2 “matrix 关闭 result cache；生产 active channel 标 cache_hit”是合理的缓存替代语义，
  无需保存原始执行明细；但它不能替代并发 leg 的执行状态聚合契约。
- **决策**: `accepted`，v2 尚未完全关闭。
- **必须修订**: 每个 leg 返回 immutable `ChannelExecution`，sync/async coordinator 显式聚合为
  `RetrievalExecutionInfo`；worker/task 不直接 mutate ContextVar。最终 typed result 或 caller 在单一 owner 处
  设置/读取 ContextVar，随后 token reset。cache hit 可由 canonical policy 重建 active=`cache_hit`、
  inactive=`disabled`，不得声称原始 contributed/no-match。

### F-05 — 宿主环境与位置效应

- **步骤 1 核验**: critic 事实为真；独立路径不等于宿主/硬件/位置完全隔离。
- **步骤 2 触发**: `.env` 重注入见 F-02。另有规范不一致：REQ-RBE-003 仍要求至少 forward/reverse，
  `design.md:84-88` 却将 final `balanced` 定义为 cyclic Latin；普通 cyclic Latin 不必包含 reverse order。
- **步骤 3 成本**: 影响 High；环境封口和 schedule 契约修订成本低至中。
- **步骤 4 范围**: 属顺序独立与可复现性核心范围。
- **步骤 5 替代**: v2 的 child effective config、完整 worktree fingerprint、position delta 和 balanced position
  coverage 对 OS page cache/GPU 热状态是等价且更诚实的缓解；无需声称能物理清空宿主缓存。
- **决策**: `accepted`，v2 尚未完全关闭。
- **必须修订**: 合并 F-02 的 dotenv 封口；并二选一：
  - 将 REQ-RBE-003 改成 quick=forward/reverse、promotion=每 variant 每 position 等次数的 balanced schedule；或
  - 使用明确包含 forward/reverse 且保持 position balance 的 Williams/成对设计。
  最终 summary 要区分 quality order drift、latency position effect 和不可控制的 host-cache 边界。

### F-06 — 有限资源边界

- **步骤 1 核验**: critic 事实为真；v1 只有数量上限且 subprocess 无 timeout。
- **步骤 2 触发**: full corpus、挂起模型或 Milvus 均可触发。
- **步骤 3 成本**: 影响 High；preflight、timeout 与 process-group cleanup 成本中等，必须修。
- **步骤 4 范围**: 属有限算力 benchmark 的本质范围。
- **步骤 5 替代**: 仅文档提示或人工观察不等价。
- **决策**: `accepted`。
- **v2 核验**: `design.md:176-183` 已同时定义 workload/disk/output/candidate/wall-time 边界和
  SIGTERM→SIGKILL；`design.md:220,235` 定义失败状态与 deterministic timeout 测试。在设计层关闭。
- **实现门禁**: 所有上限必须有非 `None` 的安全默认值；若允许显式放宽，requested/effective limit 和 override
  必须进入 manifest，仍不得越过硬性 variant/dataset/repeat 上限。

### F-07 — Dataset 与 Summary 原子发布

- **步骤 1 核验**: critic 事实为真；逐文件 replace 不是 bundle transaction。
- **步骤 2 触发**: 任一文件/summary 写入或 pointer 切换时崩溃均可触发。
- **步骤 3 成本**: 影响 High；generation + pointer 成本中等。
- **步骤 4 范围**: 属 adapter/matrix 持久化契约。
- **步骤 5 替代**: v2 generation directory + manifest-last 是正确替代，比覆盖三个固定文件更强；但断电耐久
  仍需要目录 fsync。
- **决策**: `accepted`，v2 尚未完全关闭。
- **必须修订**: generation directory rename 后 fsync 其父目录，再发布 pointer；`current.json` temp replace 后
  fsync pointer 父目录；原子 summary checkpoint 同样执行 file fsync + parent-dir fsync。unsupported platform
  必须给明确 degraded durability/拒绝策略，不能静默声称 crash durable。fault injection 覆盖 parent-dir fsync。

### F-08 — 阶段化性能协议

- **步骤 1 核验**: critic 事实为真；v1 缺索引、存储、RSS/QPS，且 `cold_ms` 名称错误。
- **步骤 2 触发**: v2 已补 `design.md:185-200` 的阶段指标，但 baseline 摄入仍欠定义。当前
  `run_benchmark.py:71-118` 对所有 variant 同时写 Milvus dense 与 BM25；因此 `bm25_only` 即使查询期不碰
  dense，ingest/index time、GPU/RSS/store bytes 仍可能包含 dense embedding/Milvus index 成本。
- **步骤 3 成本**: 影响 High；按 active policy 构建索引或拆分成本归属的成本中等。
- **步骤 4 范围**: 属用户明确要求的索引与资源性能比较。
- **步骤 5 替代**: 如果为了 corpus snapshot 保留共同 Milvus 摄入，必须将其标为 shared preparation 并从
  variant-specific index cost/Pareto 排除；否则不等价。
- **决策**: `accepted`，v2 尚未完全关闭。
- **必须修订**: baseline manifest 明确每个 variant 的 ingest/index stages：BM25-only 不构建 dense index，
  dense-only 不构建 sparse/BM25，native hybrid 构建相应字段；或定义一次共同 corpus preparation 加各 variant
  独立 index build，并分别计时/计空间。`first_query_ms`、`cold_start_ms` 与 ingest 指标必须引用同一明确边界。

### F-09 — 强制对抗测试

- **步骤 1 核验**: critic 事实为真；v1 测试矩阵不足。
- **步骤 2 触发**: 缺 guard/cache/offline/atomic 任一测试即可让 happy-path 误绿。
- **步骤 3 成本**: 影响 High；新增 fault-injection/E2E 成本中等。
- **步骤 4 范围**: 属仓库强制测试门禁。
- **步骤 5 替代**: benchmark 数值不能替代永久 regression test。
- **决策**: `accepted`。
- **v2 核验**: `design.md:224-245` 已逐 F-01～F-10 定义单元、fault injection、documents-route E2E 与真实
  child；`tasks.md:15-42` 将 finding 回指到红绿任务。在设计层关闭。tracking 最终仍须给每个 finding 独立
  永久测试名和红→绿证据。

### F-10 — 抽样、Slug 与 Source Fingerprint

- **步骤 1 核验**: critic 事实为真；v1 未规定 query sampling 与 collision-proof identity。
- **步骤 2 触发**: iterator 顺序变化、`a/b`/`a-b` 和下载失败均是常规路径。
- **步骤 3 成本**: 影响 High；hash selection/slug/summary 成本低，必须修。
- **步骤 4 范围**: 属 adapter 确定性和审计范围。
- **步骤 5 替代**: 仅依赖终端日志不等价。
- **决策**: `accepted`。
- **v2 核验**: `design.md:125-138` 明确 query hash、graded qrels、doc scan boundary、hash-suffixed slug 和
  fingerprint；`design.md:140-157` 定义原子 conversion summary；`design.md:238` 要求 shuffle 后 byte-identical。
  在设计层关闭。

## 必须先完成的 v2.1 修订

| Blocker | 关联 finding | 最小修订 |
|---|---|---|
| B-01 | F-02/F-05 | child 设置 `PYTHON_DOTENV_DISABLED=1`，以 env + repository `.env` 双 canary 验证零 secret/零网络 |
| B-02 | F-03 | 分离 `public_quality depth>=100` 与生产性能 run；official gate 校验实际 retrieved depth |
| B-03 | F-04 | leg 返回 immutable execution info，由 coordinator 聚合；禁止 worker/task mutate ContextVar |
| B-04 | F-05 | 对齐 REQ-RBE-003 与 promotion balanced schedule，明确 forward/reverse 是否属于最终设计 |
| B-05 | F-07 | generation/pointer/summary replace 后 fsync 父目录，补断点故障测试 |
| B-06 | F-08 | 明确 active-channel index build/cost attribution，防 BM25-only 计入 dense index 成本 |

上述六项都在当前范围内，不能转 backlog。修订后无需重新发散需求，但正式 tracking 在实现前必须将其映射
到 design 行号与测试任务。

## 范围外问题清单

无。critic 的十条 finding 均属于本设计范围，没有可诚实转出的历史 BUG。

## 诚实承认的有限边界

- balanced schedule 只能平衡位置效应，不能真正清空 OS page cache 或 GPU driver 状态；必须报告 position/
  hardware fingerprint，不能宣称完全物理隔离。
- Nano-BEIR full 与 MIRACL sampled 仍不能替代私域人工 qrels；私域 golden 是最终 promotion gate。
- MIRACL sampled 输出虽小，源 cache/scan 成本仍可能较高；`--max-doc-scan` 截断必须进入 metadata。
- model fingerprint 是 identity attestation，不天然等于完整 checkpoint 内容证明；应记录 revision/manifest hash。
- synthetic visual 仍只验证接线与降级，不能作为真实 ColPali promotion 证据。

## Merge Gate

当前 **不允许进入编码**：B-01～B-06 尚未写入 design v2.1。完成修订并由 defender 快速复核后，才可将
F-02/F-03/F-04/F-05/F-07/F-08 标为 design-closed；所有 finding 的最终 `closed` 仍需实现 commit、验证测试、
永久回归测试和 tracking 四列齐全。

## v2.1 Gate Recheck — 2026-07-16

### B-01～B-06 Recheck

| Blocker | 复核证据 | 结果 |
|---|---|---|
| B-01 | `design.md:95-110,261-262` 已强制 `PYTHON_DOTENV_DISABLED=1`、active-only checkpoint preflight、宿主 env + repository `.env` 双 canary 与 offline attestation；`tasks.md:32-33` 回指测试 | design-closed |
| B-02 | `design.md:181-191` 已分离 `public_quality depth>=100` 与 `production_performance`，official gate 校验 requested/effective depth，禁止合并 Pareto；`tasks.md:41-43` 回指 evaluator/run-class | design-closed |
| B-03 | `design.md:39-56` 已规定 immutable `ChannelExecution`、caller coordinator 聚合和 typed outcome，worker/task 不 mutate ContextVar；`design.md:265-266` 有并发测试 | design-closed |
| B-04 | `requirements.md:39-41` 与 `design.md:87-93` 已统一 quick=forward/reverse、promotion=balanced every-position；`tasks.md:26-27` 回指 | design-closed |
| B-05 | `design.md:119-124,149-167` 已覆盖 summary/generation/pointer 的 file + parent-dir fsync 和 unsupported-platform 语义；`design.md:269-270`、`tasks.md:32-33` 回指 fault injection | design-closed |
| B-06 | `design.md:217-227` 已按 active policy 定义 BM25/dense/hybrid/contextual index build 与 shared preparation 成本归属；`design.md:271-272`、`tasks.md:42-43` 回指 | design-closed |

### 唯一残余规范不一致

- **R-01 — F-03 evidence classification acceptance**: `design.md:9-14` 定义
  `official-comparable | full-local | sampled-local | synthetic` 四级证据，但
  `requirements.md:103` 仍只要求 `official-comparable、sampled、synthetic` 三类，遗漏 `full-local` 且命名未与
  `sampled-local` 对齐。这会允许实现通过 acceptance 时丢失“完整 corpus、非官方协议”的关键诚实边界。
- **最小修订**: 将 Acceptance Criteria 最后一条改为：
  “结果报告明确区分 `official-comparable`、`full-local`、`sampled-local`、`synthetic` 四类证据。”

### Recheck Gate

F-01～F-10 的实质设计风险均已有可实现、可验证契约；但按 Spec-Gate 严格口径，编码入口仍有 **R-01
一处文档一致性阻塞**。完成上述一行修订后，无需再次发散评审，可直接将 F-01～F-10 标为
`design-closed / implementation-pending` 并进入红测试阶段。最终 finding 仍不能在无 commit/验证/永久回归
证据时标为 `closed`。
