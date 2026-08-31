# Critic 报告 — retrieval-benchmark-expansion

**评审对象**: `docs/specs/retrieval-benchmark-expansion/design.md` (v1)
**评审模式**: 完整 critic + STRIDE（检索热路径、benchmark 隔离、路径/环境边界）
**评审日期**: 2026-07-16

## 摘要

- Critical: 3 条
- High: 7 条
- Medium: 0 条
- Low: 0 条
- 结论: 必须修订出 v2；所有 Critical/High 在编码前完成 defender 裁决与 tracking 闭环。

## Confirmed Strengths

- `praise (non-blocking)`: 独立 Milvus/collection/registry/RAPTOR/visual/cache namespace、
  `shell=False`、variant env allowlist 和默认不覆盖输出，方向正确，能切断大部分显式跨 run 污染。
- `praise (non-blocking)`: 设计明确区分 sampled 与 synthetic 证据、不自动修改生产默认值，并保留
  `unavailable != 0`，符合现有评测和热路径降级不变量。
- `praise (non-blocking)`: adapter 采用流式文档读取与确定性负例 hash，适合封闭部署的有限内存场景。

## Findings

### F-01 — 通道关闭契约没有覆盖 fallback、planner 与后处理

- **id**: F-01
- **severity**: Critical。REQ-RBE-005/006 的目标在方案下仍可复现：异常分支可以重新调用已关闭的
  dense leg，且 `bm25_only` 常规路径仍可能执行 dense embedding 驱动的 MMR。符合严重性量表 §2
  “方案未闭合目标 BUG”，并触及混合检索热路径降级不变量。`issue (blocking, must-fix)`。
- **location**: `docs/specs/retrieval-benchmark-expansion/design.md:16-25,36-46,108-119,171-177`；
  `core/retrieval/hybrid_retriever.py:479-520,563-570,1039-1052,1128-1235`；
  `core/retrieval/planner.py:90-107,162-293`；触及根规范 §0.3/§0.5、`core/AGENTS.md` §3、
  `tests/AGENTS.md` §4。
- **symptom**: 仅在“创建 leg”位置判断开关不足以闭合契约。同步路径任一融合/重排/MMR 异常后仍会
  unconditional dense fallback；planner 的 dense/sparse weight、retry action 和融合归一化不知道通道已
  disabled；示例 `bm25_only` 只关闭 dense retrieval/reranker，默认 MMR 仍会取得 embedding 并执行查询
  前向。复杂 filter 下若 fallback 或可选通道没有再次经过 capability 判定，还可能把“禁用”变成不安全
  的替代通道。
- **impact**: baseline 名称与实际算法/资源消耗不一致，dense/sparse call-count 和 query-forward 证据不可
  信；双关闭时还可能触碰 dense manager，而不是稳定返回 empty/degraded。生产热路径的显式关闭也无法
  作为可靠回滚开关。
- **root_cause**: 设计把开关视为 leg 调度局部条件，没有定义贯穿 planner、query representation、
  fallback、fusion、retry、post-processing 和 diagnostics 的统一 active-channel policy。
- **recommendation**: 在 `design.md` §2.1 增加 `ActiveChannelPolicy` 契约，并要求
  `HybridRetrieverConfig`、`RetrievalPlanner`、sync/async/thread-pool、所有 catch fallback、
  `_needs_shared_representation`、RRF 权重归一化与 retry 都只读取该策略；disabled 通道权重必须为 0，
  不得因异常复活。为 named baseline 给出完整而非增量的算法定义：`bm25_only` 同时关闭 workflow、native
  sparse、reranker、MMR/query-reuse、contextual/optional channels；若需要保留任一后处理，名称必须明确
  表达。每个存活通道仍须通过 `FilterScope` capability，unsupported 时 fail-closed，不得去掉 filter。
- **verification**: 在 `tests/unit/test_retrieval_benchmark_channels.py` 注入 RRF、reranker、MMR 异常，分别
  对 sync/async/parallel 断言 disabled leg 的 mock call-count 恒为 0；断言 `bm25_only` 不访问
  `dense_manager`、query forward 为 0；覆盖 planner retry、双关闭+可选通道、SOURCE_SET/复杂 Milvus
  filter，证明无 unfiltered fallback 且 empty 的相关性为 `None`、diagnostics 为 degraded/disabled。
- **status**: open

### F-02 — “离线且私域不外发”没有被 runner 强制执行

- **id**: F-02
- **severity**: Critical。当前 `EMBEDDING_PROVIDER=auto` 在缺少本地模型依赖时会解析为 DashScope API；
  runner 若继承宿主环境即可把私域 query/corpus 发往第三方，违反 REQ-RBE-016/017 和安全基线中的
  PII/敏感数据下发不可降级项。符合严重性量表 §2(c)。`issue (blocking, must-fix)`。
- **location**: `docs/specs/retrieval-benchmark-expansion/design.md:48-50,92-99,122-128`；
  `utils/env_utils.py:115-167,208-217`；`scripts/run_paired_benchmark.py:313-338`；触及根规范 §8
  Secret/Env、PII 与信息泄露边界。
- **symptom**: 设计只禁止 LLM/judge 和“运行期模型下载”，没有规定 embedding/reranker 必须是已缓存的
  local provider，也没有规定从 child env 删除 API key/base URL。现有 paired runner 使用
  `os.environ.copy()`；在 API-only 环境或宿主设置 `EMBEDDING_PROVIDER=api` 时，benchmark 会进行外部
  embedding 调用。Hugging Face offline flags 也未被固定，本地 model id 缓存缺失时仍可能联网下载。
- **impact**: 私有 golden、问题与文档片段可能离开封闭环境；同一实验依赖外部服务版本、网络和配额，
  不再可离线复现，且失败时可能被错误解释成检索性能退化。
- **root_cause**: “不调用 LLM”被误当作“无外部模型调用”，缺少 child-process 的最小环境、local-only
  preflight 与网络失败语义。
- **recommendation**: 在 `design.md` §2.2/§5 明确 matrix child 使用最小环境白名单而非完整继承；强制
  `EMBEDDING_PROVIDER=local`、本地 embedding/reranker 路径存在且 fingerprint 可读，设置
  `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`，并从 child env 移除所有 `*_KEY`、远端 base URL 和
  LLM/judge 配置。缺本地 checkpoint/dependency 时应在启动任何 run 前标记 `unavailable`，不得自动退到
  API。private golden 的 promotion eligibility 必须附 `network_mode=offline` attestation。
- **verification**: 在 `tests/unit/test_benchmark_matrix_security.py` 放入 canary API key、
  `EMBEDDING_PROVIDER=api` 和恶意远端 URL，断言生成的 child env 不含这些值；mock HTTP/socket 断言
  零网络调用；删除本地 checkpoint 后应得到结构化 unavailable、无子进程/无 API fallback，且日志和
  summary 不出现 canary。
- **status**: open

### F-03 — `official_comparable` 判定与现有 evaluator 协议不相容

- **id**: F-03
- **severity**: Critical。即便使用 full corpus/unlimited query，现有 `run_benchmark.py` 仍把 qrels 降为
  binary expected ids，并以 `top_k=4` 计算自定义 MRR/nDCG；这不能与 BEIR/MIRACL 的标准 cutoff、graded
  qrels 协议直接比较。设计仍会把不可比较结果标为可比较，核心评测目标未闭合。`issue (blocking,
  must-fix)`。
- **location**: `docs/specs/retrieval-benchmark-expansion/design.md:8-12,52-59,65-90,130-135`；
  `scripts/run_benchmark.py:222-241,320-357,427-487`；触及 REQ-RBE-008/010/011/014/021 和评测事实
  可追溯性。
- **symptom**: adapter 契约只保留“正相关 doc ids”，没有保留完整 relevance grade；runner 的 nDCG 是
  binary gain，默认 cutoff 4，而公开协议通常报告 nDCG@10、Recall@100 等。`nano-beir/*` 也只能与其
  自身 nano 协议比较，不能借 `official_comparable=true` 暗示完整 BEIR 榜单可比。
- **impact**: summary 可能把数值相近但语义不同的指标放在同一表中，形成错误 baseline/promotion 结论；
  后续用户无法判断收益来自检索算法还是 cutoff/qrels 语义变化。
- **root_cause**: “完整语料”被等同于“完整评测协议”，缺少 evaluator version、graded qrels、standard
  cutoffs、query set 和 dataset revision 的联合资格判定。
- **recommendation**: 修改 `requirements.md` REQ-RBE-010/011 与 `design.md` §2.3：sidecar 必须保留
  `qid -> {docid: relevance}`；引入 versioned public-IR evaluator，按 dataset registry 固定标准 metric
  cutoffs，并记录 dataset revision、split、query count、qrels hash、evaluator/version。只有 full corpus、
  完整标准 query set、完整 grades、标准 cutoffs 且无 `dedup_source`/query limit 时才允许
  `official_comparable=true`。若本轮只复用现有 runner，则字段应改为 `corpus_complete=true` 且一律
  `official_comparable=false`。
- **verification**: 在 `tests/unit/test_prepare_ir_benchmark.py` 使用 graded qrels fixture；在
  `tests/unit/test_public_ir_metrics.py` 用已知 run 对照 `ir_measures`/TREC 期望值验证 nDCG@10、MRR@10、
  Recall@100；改变 cutoff、丢失 grade、限制 query 或使用 nano/sample 时均断言 promotion-ineligible。
- **status**: open

### F-04 — cache identity 与 channel diagnostics 契约欠定义

- **id**: F-04
- **severity**: High。检索 cache 属热路径组件，当前方案只写入 dense/sparse on/off，未覆盖决定结果的
  其余配置，也没有定义 cache hit 时如何还原“disabled/unavailable/executed”。符合严重性量表 §2 的
  缓存失效路径未闭合。`issue (blocking, must-fix)`。
- **location**: `docs/specs/retrieval-benchmark-expansion/design.md:23-25,52-59,101-106`；
  `core/retrieval/hybrid_retriever.py:374-423,461-471,609-620`；触及 `core/AGENTS.md` §3 检索缓存和
  `tests/AGENTS.md` §4。
- **symptom**: 非 workflow cache identity 当前主要包含 query/filter/budgets/plan/retry/version；设计没有列出
  native sparse vs BM25、weights/RRF、reranker+model、MMR/time-decay、contextual generation、optional
  channels/model revision 等字段。仅从返回文档推断 channel counts 无法区分“执行但无命中”“不可用”
  “disabled”和“cache hit”。
- **impact**: 同进程不同 config 或索引/模型切换可能复用错误结果；诊断可能把缓存结果当作本次通道实际
  执行，破坏 baseline call-count、降级率和 `unavailable != 0` 证据。
- **root_cause**: cache 被设计为 `list[Document]` 的结果缓存，而 benchmark 又需要可审计执行元数据；两者
  没有统一的 versioned retrieval identity/result envelope。
- **recommendation**: 在 `design.md` §3 定义 canonical `RetrievalIdentity`（active channels、backend、
  weights/budgets、post-processors、model/revision、index/contextual generation、filter fingerprint、cache
  version）和 `RetrievalExecutionInfo`（每通道 `disabled|executed|no_match|unavailable|cache_hit`）。cache
  value 应保存 docs + 非敏感 execution info，或由 typed result 返回；不得依赖全局可变诊断状态。
- **verification**: 预热 cache 后依次翻转每个 identity 字段，均必须 miss；完全相同配置必须 hit。cache
  hit、通道抛错和通道无命中分别断言不同状态，且 unavailable score 为 `None`；并发请求不得串扰
  execution info。
- **status**: open

### F-05 — forward/reverse 不能单独排除宿主环境与位置效应

- **id**: F-05
- **severity**: High。常见的宿主 env、`.env`、OS page cache、GPU 热状态和共享模型缓存没有纳入隔离；
  对 7 variants 仅前序/反序也只让每个 variant 出现在两个镜像位置，延迟位置效应仍被混淆。符合 §2
  “实验顺序/缓存失效路径未覆盖”。`issue (blocking, must-fix)`。
- **location**: `docs/specs/retrieval-benchmark-expansion/design.md:48-59,130-136`；
  `scripts/run_paired_benchmark.py:221-250,313-338,374-406`；触及 REQ-RBE-002/003/016/022。
- **symptom**: allowlist 仅约束 variant 提供的键，未清除宿主中其他影响检索的 env；布尔/数值非法值
  可能被生产代码静默解释为 false/default。model/worktree fingerprint 若在 parent 进程计算，可能不是
  child 的有效配置；现有 worktree hash 也不含 untracked 文件。质量在新存储下可能稳定，但 latency 会
  受到先运行 variant 已预热模型文件、page cache 或 GPU 的影响。
- **impact**: 同一 matrix 文件在两台机器或两个 shell 中可运行成不同算法；forward/reverse 的 P95 差值
  可能被误认作 variant 性能，order-independence 通过也不能证明延迟收益来自算法。
- **root_cause**: “独立进程/路径”被当作完整实验隔离，缺少 effective-config attestation 与主机级调度
  设计。
- **recommendation**: runner 应从 canonical defaults 构造最小 child env，严格解析每个 bool/int/float 的
  值域和跨字段约束，并由 child 输出 effective config/model/index/dependency/hardware fingerprint，parent
  校验 requested==effective。worktree identity 至少覆盖 HEAD、tracked diff、相关 untracked 文件与
  `uv.lock`。forward/reverse 只作为 quick smoke；用于 latency/promotion 时采用固定 seed 的 balanced
  rotation/Williams schedule，或明确预热所有模型后随机交错独立 process repeats，并分别报告 position
  delta，不把 quality tolerance 直接套到 latency。
- **verification**: 注入冲突宿主 env、非法数值、未跟踪脚本和不同模型路径，断言 either 启动前拒绝或
  fingerprint 改变；schedule 测试证明每个 variant 在 promotion 模式覆盖相同位置次数；伪造按位置递增
  latency 时报告必须识别 position effect，而不是选择错误 Pareto winner。
- **status**: open

### F-06 — 12×12 计数上限不足以形成有限资源边界

- **id**: F-06
- **severity**: High。full corpus 可任意大，现有复用 runner 的 subprocess 没有 timeout；一个 dataset
  即可耗尽磁盘、内存或无限挂起，REQ-RBE-019 的资源耗尽目标未闭合。`issue (blocking, must-fix)`。
- **location**: `docs/specs/retrieval-benchmark-expansion/design.md:108-120,130-136`；
  `scripts/run_paired_benchmark.py:313-344,449-484`；触及 STRIDE DoS、REQ-RBE-019/023。
- **symptom**: 只限制 datasets/variants/repeats 数量，没有限制 query/doc 数、corpus bytes、候选预算、
  单 run/全局 wall time、输出/索引磁盘量、并发度或最小剩余磁盘。`subprocess.run` 未给 timeout，超时后的
  子进程组清理也未定义。
- **impact**: 本地/CI 可因大数据集、坏模型加载或 Milvus 卡死而永久挂起；半成品索引占满 `/tmp`，影响
  后续生产或测试。有限算力用户无法预估一次 matrix 的成本。
- **root_cause**: 资源预算按配置项数量而非实际工作量建模。
- **recommendation**: 在 `design.md` §6 增加 preflight workload manifest：run 数、query/doc 数、输入
  bytes、估算索引 bytes、候选上限、所需空闲磁盘；增加 `--run-timeout`、`--total-timeout`、
  `--max-corpus-docs/bytes`、`--max-output-bytes` 和默认串行/受限并发。超时必须终止整个 process group、
  关闭连接并记录 failed；超限在创建子进程/目标文件前 fail-closed，显式 override 也必须落入 metadata。
- **verification**: 用伪造超大 metadata、低磁盘、挂起 child 和超预算 candidate 配置测试启动前拒绝；
  timeout 测试用 Event/受控 fake process，不用 sleep，断言子进程组被回收、旧产物保留且 matrix 最终
  非零退出。
- **status**: open

### F-07 — 三文件 `os.replace` 不是数据集级原子发布

- **id**: F-07
- **severity**: High。adapter 一次生成 cases/corpus/metadata 三个相互引用的文件，逐文件 replace 在
  第二或第三步崩溃会留下混合代次；matrix 当前复用路径也可能在首个失败 run 直接退出而没有 promised
  failed summary。属于持久化失败路径未闭合。`issue (blocking, must-fix)`。
- **location**: `docs/specs/retrieval-benchmark-expansion/design.md:69-90,108-119`；
  `scripts/run_paired_benchmark.py:330-356,477-499`；触及 REQ-RBE-013/015/021/023。
- **symptom**: “同目录 staging + `os.replace`”只保证单文件原子性；`--overwrite` 时更可能出现新 cases +
  旧 corpus/metadata。设计称 run 非零会写入 summary，但复用实现的 `run_spec` 抛错会中断整个 loop，且
  summary 使用普通 `write_text`，完成的其他 run 也可能没有可审计汇总。
- **impact**: 下次 benchmark 可摄入与 qrels 不匹配的语料，产生看似成功的错误指标；崩溃或断电后既
  无法自动恢复旧代次，也无法证明哪些 run 已完成。
- **root_cause**: 把单文件 rename 当作多产物事务，且未定义 matrix 的增量 checkpoint/continue-on-error
  状态机。
- **recommendation**: adapter 应把一个 dataset generation 写入同一 staging directory，逐文件 flush+
  fsync、校验交叉 fingerprint 后原子发布 generation directory，并以 manifest/pointer 作为唯一可见提交
  点；overwrite 保留旧 generation 直到新 generation ready。matrix 捕获每个 run 异常、继续其他 run，
  每次状态变化都通过临时文件+fsync+replace 原子 checkpoint `summary.json`，最终有 failed 即非零退出。
- **verification**: 在每个文件写入、fsync、目录 rename、manifest 切换点注入故障，consumer 必须只看到
  全旧或全新 generation；matrix 中间 run 失败时后续 run 仍执行，summary 同时保留 success/failed，且
  任意截断 JSON 都不会成为可见最终产物。
- **status**: open

### F-08 — 性能协议缺少索引成本、吞吐量，且 `cold_ms` 语义不是真冷启动

- **id**: F-08
- **severity**: High。用户确认的性能比较包含索引时间、存储、吞吐量与冷/热延迟；requirements/design
  只保留显存和 query-forward。现有 runner 在语料 embedding/摄入后才记录第一条 query，不能称为完整
  冷启动。核心性能结论仍不完整。`issue (blocking, must-fix)`。
- **location**: `docs/specs/retrieval-benchmark-expansion/requirements.md:18-23,49-50`；
  `docs/specs/retrieval-benchmark-expansion/design.md:52-59,130-136`；
  `scripts/run_benchmark.py:71-118,360-398,507-585`。
- **symptom**: 没有 index/ingest wall time、store bytes、process RSS、sequential throughput/QPS；GPU peak 在
  ingest 后 reset，只代表 query phase。`cold_ms` 是“模型和索引已就绪后的首 query”，不包含 process
  startup、checkpoint load 或 index open/build。
- **impact**: contextual、reranker、native sparse 等方案可能以大幅增加摄入时间/磁盘/内存换取小幅质量
  收益，却仍进入 Pareto 集；所谓 cold-start 改善也可能只是标签错误。
- **root_cause**: 直接继承旧 runner 的可用字段，没有先定义阶段化性能测量协议。
- **recommendation**: 更新 REQ-RBE-008 和 `design.md` §2.2/§6，分别记录 process/model ready、corpus
  ingest/index build、index open、first-query、warm P50/P95、总 query throughput、峰值 RSS、GPU
  allocated/reserved、每个隔离 store bytes 与 query-forward；现有 `cold_ms` 改名 `first_query_ms`，只有
  新鲜进程且明确计时边界的 end-to-end 值才叫 `cold_start_ms`。Pareto 至少提供 quality-latency 和
  quality-resource 两个视图，不把缺失资源值当 0。
- **verification**: 以 fake clock/resource probe 固化阶段边界；故意增加 ingest 延迟/文件大小时相应指标
  必须变化而 warm query 不变；资源 probe 不可用时输出 `None + unavailable reason`，并验证 Pareto 不会
  将缺失值当作最优。
- **status**: open

### F-09 — 测试矩阵未覆盖规范强制的对抗路径

- **id**: F-09
- **severity**: High。热路径变更缺少若干必须的“不可用≠0”、fallback、缓存失效和 documents 路由
  写入→混合检索读出用例，符合严重性量表 §2(d) 与 `tests/AGENTS.md` §4。`issue (blocking,
  must-fix)`。
- **location**: `docs/specs/retrieval-benchmark-expansion/design.md:138-162`；
  `docs/specs/retrieval-benchmark-expansion/tasks.md:12-31`；触及根规范 §1.1、`tests/AGENTS.md` §2-§4。
- **symptom**: 当前列表只有一般 call-count/atomic write 描述，未要求：异常 fallback 不复活 disabled
  channel、warm-cache 后切 config/index、cache-hit diagnostics、复杂 filter 在每个可选通道 fail-closed、
  hostile ambient env/零网络、真实 subprocess timeout、graded qrels 标准指标、崩溃发布点、以及通过
  documents API 写入后 BM25/hybrid 可读的一致性。`sidecar` 直接摄入不能替代后者。
- **impact**: 实现可能在 happy path 全绿，却在恰好决定 baseline 可信度的失效/缓存/过滤路径回归；不
  满足仓库合并门禁。
- **root_cause**: 测试矩阵按组件罗列，没有从 Critical/High 失效模式反推具体对抗断言。
- **recommendation**: 在 `design.md` §7 与 `tasks.md` 为 F-01..F-08 各增加一条可追溯测试；单元覆盖纯逻辑
  与 fault injection，进程内 E2E 使用 `client` fixture 完成 documents route 写入→dense/BM25 读取、
  filter 和双关闭终态；小 fixture 子进程测试验证真实 env/path/timeout/summary。所有网络与外部模型均
  mock/禁止，不依赖 Ollama/远端 Milvus；保存红→绿日志。
- **verification**: tracking 中每个 Critical/High 必须有独立 regression test 名称；运行定向矩阵后再跑
  `tests/unit/ tests/e2e/`。新增测试若删除任一开关 guard、cache identity 字段、offline guard 或 atomic
  commit 点，必须稳定变红。
- **status**: open

### F-10 — 抽样 query、slug 与 source fingerprint 仍可能不确定或碰撞

- **id**: F-10
- **severity**: High。`query-limit` 是 sampled 模式常规路径，但设计只定义负例的确定性选择，没有定义
  query 选择；安全 slug 也未保证不同 dataset id 一一对应，source fingerprint 算法和 unavailable 汇总
  载体均未定义。违反 REQ-RBE-013/015/022 的常见路径可复现性。`issue (blocking, must-fix)`。
- **location**: `docs/specs/retrieval-benchmark-expansion/design.md:65-90,108-128`；触及
  REQ-RBE-010/012/013/014/015/022。
- **symptom**: 若直接取 qrels iterator 的前 N 个 query，不同 adapter/source iteration order 会得到不同
  样本；`a/b`、`a-b`、`a_b` 等 id 可能 slug 到同名，`--overwrite` 时可替换另一数据集；仅写每个成功
  dataset 的 metadata 无法为下载失败的数据集留下重复可验证的 unavailable 证据。
- **impact**: 同 seed 的样本和资源身份可漂移，已有输出可能被错误归属；外部不可用时 acceptance
  evidence 缺失，只能依赖临时终端日志。
- **root_cause**: 确定性只应用于 negative docs，没有扩展到 query selection、文件身份和批转换状态。
- **recommendation**: query 也按 `sha256(seed,dataset_id,qid)` 排序选取，并规定 ties/canonical encoding；
  slug 使用可读前缀加 dataset-id hash 后缀；source fingerprint 明确覆盖 dataset package/revision、split、
  selected qids、完整 qrels grades 和最终 corpus artifact hashes。新增原子
  `conversion_summary.json`，逐 dataset 记录 success/unavailable/failed、稳定 error code 与产物 generation，
  不记录 secret/绝对敏感路径。
- **verification**: 随机打乱 query/qrel/doc iterator 后产物 byte-for-byte 相同；构造 slug 碰撞 id 后路径
  仍唯一；模拟某个 dataset 下载失败，其他产物保持成功且 conversion summary 稳定记录 unavailable，
  重跑得到相同选择/fingerprint。
- **status**: open

## STRIDE 表

| STRIDE 类 | 评审结论 | 关联 finding |
|---|---|---|
| 欺骗 (Spoofing) | requested variant 与 child effective config 未做相互认证，标签可与实际算法不一致。 | F-01, F-05 |
| 篡改 (Tampering) | 非唯一 slug 与多文件非事务发布可形成错误代次或覆盖错误数据集。 | F-07, F-10 |
| 否认 (Repudiation) | worktree 未跟踪文件、child effective config 和失败 dataset 若无稳定 summary，实验无法完整追溯。 | F-05, F-07, F-10 |
| 信息泄露 (Info Disclosure) | `auto/api` embedding 和继承的 API key 可把私域 query/corpus 发往第三方。 | F-02 |
| 拒绝服务 (DoS) | dataset/variant 数量上限不能限制 corpus 大小、磁盘和无限子进程。 | F-06 |
| 权限提升 (Elevation) | 本功能为本地 CLI，不新增 Admin/租户授权面；argv list + `shell=False` 的现有方向可接受。 | 无新增 finding |

## Merge Gate

- F-01、F-02、F-03 必须在 design v2 中修订后才可编码。
- F-04..F-10 必须 `closed` 或由 defender 给出满足同一不变量的可验证等价方案。
- tracking 必须为每条 Critical/High 填入 design decision、实现 commit、验证测试和永久回归测试；仅有
  benchmark 结果不能替代上述闭环。
