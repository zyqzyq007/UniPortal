# Retrieval Benchmark Expansion — Design v2.1

## 1. Revision and Decision Summary

v2.1 接受 critic F-01..F-10、preliminary DP-01..09 与 defender B-01..06 的事实风险。新增统一 active-channel policy、
local-only child environment、graded-qrel public evaluator、balanced schedule、实际资源预算、generation
bundle 原子发布和阶段化性能测量。生产默认仍不改变。

证据分级：

1. `official-comparable`：完整 corpus/query/graded qrels、registry 固定标准 cutoff 和 evaluator version。
2. `full-local`：完整本地 corpus，但协议或 cutoff 不满足公开 allowlist；只与本仓库同协议比较。
3. `sampled-local`：qrels + deterministic negatives；禁止公开榜单/promotion 表述。
4. `synthetic`：只证明算法接线与降级。

## 2. Active Retrieval Policy

### 2.1 Canonical Policy

`HybridRetrieverConfig.active_policy()` 返回不可变 `ActiveChannelPolicy`：

- `dense`、`sparse`、`graph`；
- sparse backend (`native_m3|bm25|disabled`)；
- `reranker`、`mmr`、`time_decay`、`candidate_funnel`、`contextual_index`；
- weights/budgets 与 model/index fingerprints。

新环境变量均保持兼容默认：

- `RETRIEVAL_DENSE_ENABLED=true`
- `RETRIEVAL_SPARSE_ENABLED=true`
- `RETRIEVAL_MMR_ENABLED=true`
- `RETRIEVAL_TIME_DECAY_ENABLED=true`

policy 是 sync/async/thread-pool、planner weights、query representation、RRF normalization、retry、catch
fallback 和 diagnostics 的唯一事实来源。disabled 通道权重固定为 0，异常不得复活；fallback 只能选择
仍 active 且满足 `FilterScope` capability 的通道。双主通道关闭时，可选通道仍按原 filter 契约运行；均无
证据则返回 empty/degraded，score 保持 `None`。

### 2.2 Request-local Execution Info

每个 leg 返回不可变 `ChannelExecution(results, status)`；sync/async/thread-pool coordinator 在 caller
线程/任务中显式聚合为不可变 `RetrievalExecutionInfo`，worker/task 不修改共享 ContextVar 或可变对象。
内部 `retrieve_with_info/aretrieve_with_info` 返回 typed outcome；兼容 `retrieve/aretrieve` 仅返回 documents。
workflow 和 benchmark 使用 typed outcome，单一 caller owner 读取 execution info 后结束作用域，不写实例属性。

execution info 包含：

- identity fingerprint；
- cache hit/miss；
- dense/sparse/graph 的 `disabled|executed|contributed|unavailable_or_no_match|cache_hit`；
- active post-processors。

因现有各 leg 有意把异常安全归一为空结果，v2.1 不伪造 `no_match` 与 `unavailable` 的精确区分，沿用项目
已有 `unavailable_or_no_match` 语义。matrix 强制关闭 retrieval result cache，保证 call-count/latency 是
live execution；生产 cache hit 则 active 通道标 `cache_hit`、disabled 仍为 `disabled`。ContextVar 并发
测试证明请求间不串扰。

### 2.3 Cache Identity

canonical identity 包含：active channels/backend、weights、RRF/budgets、reranker+revision、MMR/time-decay、
candidate/contextual generation、optional flags、embedding fingerprint、filter fingerprint、retry/plan、
index/cache version。任何字段翻转必须 cache miss。

## 3. Baseline Definitions

`data/benchmark/retrieval_baselines.yaml` 使用完整配置而非增量猜测：

| Variant | Exact stages |
|---|---|
| `bm25_only` | workflow off；dense/native sparse/reranker/MMR/time-decay/optional/contextual off；BM25 on |
| `dense_only` | workflow off；dense on；sparse/reranker/MMR/time-decay/optional/contextual off |
| `hybrid_rrf` | workflow off；dense + native sparse；reranker/MMR/time-decay off；固定 budgets |
| `hybrid_reranker` | hybrid RRF + reranker；MMR/time-decay off；固定 budgets |
| `production_legacy` | workflow off；当前生产 reranker/MMR/time-decay 与固定 budgets |
| `workflow` | production workflow；frontier optional channels off |
| `workflow_funnel` | workflow + explicit candidate/rerank/selection/final budgets |
| `workflow_contextual` | workflow + contextual index；独立 collection，证据单列 |

summary 输出完整 effective stage fingerprint，不能从名称推断算法。所有 variant 显式关闭未比较的
ColBERT/RAPTOR/PPR/visual/query-transform/graph。

## 4. Matrix Runner

新增 `scripts/run_benchmark_matrix.py`，复用 paired runner 的 store/corpus snapshot 逻辑但不继承其完整
宿主环境。

### 4.1 Configuration and Schedule

- YAML variant env 严格 allowlist、类型和值域校验；重复名、未知键、跨字段非法组合在启动前拒绝。
- `quick` 使用 forward/reverse，仅作开发 smoke，不允许用于最终 latency/Pareto/promotion。
- `balanced` 使用 deterministic cyclic Latin schedule；N 个 variant 产生 N 个 order，每个 variant 在每个
  position 恰好一次。最终 latency/Pareto 只接受 balanced 结果。
- quality order-independence 比较同 variant 的全部 order；latency 单列 position delta，不套 quality tolerance。

### 4.2 Local-only Child Environment

child env 从最小 allowlist 构造，只保留运行所需的 `PATH/HOME/LANG/TMPDIR/CUDA_VISIBLE_DEVICES/
LD_LIBRARY_PATH/XDG_CACHE_HOME/HF_HOME/TORCH_HOME` 等非敏感宿主字段，并强制：

- `EMBEDDING_PROVIDER=local`；embedding/reranker path 必须是已存在本地目录；
- `PYTHON_DOTENV_DISABLED=1`，阻止 `utils/env_utils.py` 从仓库 `.env` 重新注入被清除的 key/URL；
- `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`HF_DATASETS_OFFLINE=1`；
- `RETRIEVAL_CACHE_ENABLED=false`；LLM/judge/query-transform/所有未比较 optional channel 关闭；
- 删除所有 `*_KEY`、`*_TOKEN`、proxy、remote base URL/index URL；summary 不记录值。

preflight 在任何 run 前导入 local dependencies、仅验证该 variant active 的 checkpoint，并验证 embedding/
reranker fingerprints。安全测试同时在宿主 env 与临时仓库 `.env` 放置不同 canary key/remote URL，child
effective attestation 必须给出 `dotenv_disabled=true`、`network_mode=offline` 且两个 canary 均不可见。
缺失时写结构化 `unavailable`，不启动 child、不回退 API。private golden 只有
`network_mode=offline` attestation 才可 promotion eligible。

### 4.3 Complete Store Isolation

每个 run 独立 Milvus、collection、embedding registry、RAPTOR、visual index/assets、cache namespace，另给
`documents.graph_store.DEFAULT_DB_PATH`/backup 增加 `GRAPH_STORE_DB_PATH`/
`GRAPH_STORE_BACKUP_PATH` 环境注入并隔离。默认 matrix 强制 graph off。subprocess 显式
`shell=False, start_new_session=True`。

### 4.4 Checkpoint and Failure State

matrix 捕获单个 run 失败并继续后续 run。每次状态变化都以 temp+flush+fsync+replace 原子 checkpoint
`summary.json`，replace 后 fsync parent directory。最终存在 failed/unavailable、schedule 不平衡或
effective config 不匹配时返回非零；成功 run 永久保留。summary 禁止 NaN/Infinity。若平台不支持目录
fsync，crash-durable 模式启动前拒绝；显式 best-effort 模式必须在 summary 标 `durability=degraded`。

## 5. Public IR Adapter and Evaluator

### 5.1 Dependency Profile

新增 `benchmark` optional extra，直接锁定 `ir-datasets==0.6.1` 与 `ir-measures`。真实本地检索命令使用
`uv sync --extra local-models --extra benchmark`。adapter 显式 `--cache-dir`，设置 `IR_DATASETS_HOME`；
`--offline` 只读缓存。下载失败不阻塞其他 dataset。

### 5.2 Deterministic Selection

新增 `scripts/prepare_ir_benchmark.py`：

- query 按 `sha256(seed|dataset_id|qid)` 排序选取；
- 保留 `qid -> {docid: relevance_grade}` 全量 qrels；
- stable doc id 作为 `chunk_id` 写入 Milvus dynamic field并加入 search output fields，公共评分永不依赖正文
  reverse lookup；重复正文与超过 4,000 字正文仍以 doc id 评分；
- `full` 流式读取完整 corpus；
- `qrels-plus-negatives` 必含所选 query 全部正例，负例先从其他 qrel docs 确定性选择，不足时在
  `--max-doc-scan` 内做 hash reservoir；不得为小输出无界扫描 MIRACL 493 万文档。

dataset slug 为可读前缀 + dataset-id SHA-256 后缀，避免 `a/b`、`a-b`、`a_b` 碰撞。source fingerprint
覆盖 package/version、dataset id/revision/split、selected qids、graded qrels、corpus hashes。

### 5.3 Generation Bundle Atomicity

每个 dataset 输出：

```text
<out>/<slug>/
  generations/<fingerprint>/
    benchmark.yaml
    benchmark_corpus.yaml
    qrels.json
    manifest.json
  current.json
```

完整 generation 先写 sibling staging directory，每个文件 flush+fsync，交叉 hash 校验后原子 rename；
rename 后 fsync `generations/` parent；`current.json` 作为 manifest-last commit marker 以
temp+fsync+replace 切换并 fsync dataset parent。失败只删除 staging，旧 current 继续可见。批量
`conversion_summary.json` 同样执行 file fsync + replace + parent-dir fsync，记录
success/unavailable/failed 与稳定 error code，不含 secret。

### 5.4 Versioned Public Evaluator

新增 `scripts/public_ir_metrics.py`，使用 `ir_measures` 对稳定 `(qid, docid, score/rank)` run 计算 registry
allowlist：

- BEIR/Nano-BEIR：`nDCG@10`、`RR@10`、`Recall@100`；
- MIRACL：`nDCG@10`、`Recall@100`。

evaluator 记录 version、cutoffs、qrels hash 和 query count。只有 full corpus、完整标准 query/qrels、标准
split/cutoff、无 limit/dedup 且 dataset registry 明确允许时为 `official_comparable=true`；Nano 结果单列
Nano 协议，不能冒充完整 BEIR。其他情况一律 false。

公开评测与生产性能严格分成两个 run class：

- `public_quality`：registry 指定 `evaluation_depth>=max(metric cutoff)`，当前至少 100；candidate、rerank、
  selection 和 output depth 均不得低于 evaluation depth，输出稳定 `(qid, docid, score)`。official gate 校验
  requested/effective retrieval depth 和 evaluator cutoff；实际返回少于 100 条可作为算法结果，但不得由
  runner 截断造成。
- `production_performance`：使用真实生产 final/candidate budgets，仅用于实际延迟、吞吐量和资源。

两类 run 不合并成同一 Pareto observation；public quality 表与 production performance 表通过 variant
fingerprint 关联。`run_benchmark.py` 输出首个 repeat 的 ranked qid/docid run，质量聚合仍保留原 harness
指标。Milvus `extra_output_fields` 增加 `chunk_id`，确保 stable id 贯穿摄入与检索。

## 6. Performance and Resource Protocol

### 6.1 Workload Preflight

上限同时约束：12 datasets、12 variants、3–10 repeats、query/doc count、corpus bytes、candidate/final budgets、
估算 store bytes、最小空闲磁盘、单 run timeout、total timeout、max output bytes。默认串行。

CLI：`--run-timeout`、`--total-timeout`、`--max-corpus-docs`、`--max-corpus-bytes`、
`--max-output-bytes`、`--min-free-disk-gb`。超限在创建 run dir/child 前拒绝。timeout 用 process group
SIGTERM→SIGKILL，禁止 sleep 测试，使用 fake process/Event。

### 6.2 Stage Metrics

每个 run 分别记录：

- process/subprocess wall、model/retriever ready；
- corpus ingest/index build time；
- isolated store bytes；
- `first_query_ms`（替代误导性的 `cold_ms`）与 warm P50/P95；
- total query throughput/QPS；
- peak RSS、GPU allocated/reserved；
- query embedding forwards；
- resource probe unavailable reason。

索引构建遵循 active policy，而不是所有 variant 共用统一 dense 摄入：

- `bm25_only` 只构建 BM25，不创建/embedding Milvus dense index；
- `dense_only` 只构建 dense Milvus，不构建 native sparse/BM25；
- `hybrid_rrf/hybrid_reranker/production/workflow` 按 effective sparse backend 构建 dense+native sparse 或
  dense+BM25；
- contextual variant 在其独立 index build 阶段计入 contextual 成本。

matrix snapshot verifier 根据 manifest 的 active stores 校验：BM25-only 验证输入 doc-id/hash 和摄入计数，
不错误要求 Milvus 文件；其他 variant 校验实际声明的 store。共同的数据下载/解析可列为
`shared_preparation_ms/bytes`，但不得计入 variant-specific index cost 或 Pareto。

保留 `cold_ms` 仅作为兼容 alias，并标 deprecated。只有从新鲜 child 启动到首结果的明确边界才命名
`cold_start_ms`。Pareto 输出 quality-latency 和 quality-resource 两个视图；缺失值不参与该资源维度，永不
当 0。

## 7. Provenance

worktree fingerprint 覆盖 HEAD、tracked binary diff、porcelain status、相关 untracked 文件内容和
`uv.lock`。child 输出 effective config/model/index/dependency/hardware fingerprint，parent 校验
requested==effective。最终 promotion benchmark 要求 clean committed feature SHA；开发期脏树结果标
`promotion_eligible=false`。

## 8. Failure and Degradation Matrix

| Failure | Safe behavior |
|---|---|
| disabled channel | 全路径不调用，diagnostics=`disabled` |
| active leg exception/no match | 存活 leg 继续，状态=`unavailable_or_no_match`，无 0 分 |
| both primary channels off | optional channel 继续；否则 empty/degraded |
| local checkpoint/dependency missing | matrix preflight unavailable，无 child/API fallback |
| hostile ambient env | 丢弃 secret/remote provider，以 canonical env 运行 |
| dataset/qrel/doc invalid | generation 不发布，summary 记录稳定错误 |
| bundle publish failure | 旧 generation 继续可见 |
| one run timeout/failure | kill process group，checkpoint failed，继续其他 run，最终非零 |
| resource probe unavailable | `None + reason`，不参与 Pareto 该维度 |
| visual real model absent | synthetic/OCR 仍 promotion-ineligible |

## 9. Test Matrix

### Unit and Fault Injection

- F-01：sync/async/parallel、RRF/reranker/MMR 异常、planner retry 均不复活 disabled leg；BM25-only query
  forward=0；双关闭 unavailable != 0；复杂 filter fail-closed。
- F-02：宿主 env + repository `.env` 双 canary key/API endpoint 被清除；dotenv disabled；active local
  checkpoint 缺失时零 child/零 network。
- F-03：graded qrels known run 对照 `ir_measures` 的 nDCG@10/RR@10/Recall@100；public_quality depth
  不足、cutoff/limit/nano/sample 不得错误 promotion；production run 不冒充 Recall@100。
- F-04：每个 identity 字段翻转 cache miss；immutable leg result 在 sync/async/thread-pool coordinator
  聚合，cache hit/disabled/unavailable_or_no_match 并发不串扰。
- F-05：balanced schedule 每个 variant 覆盖每个 position；position latency trap 被报告。
- F-06：corpus bytes/low disk/hanging child/total timeout/process-group cleanup。
- F-07：每个 file/parent-dir fsync、rename、pointer 点故障，只见全旧或全新；run 失败后续继续且 summary
  可读；unsupported directory fsync 不得伪装 crash durable。
- F-08：fake clock/size/RSS/GPU probe 验证阶段边界和缺失值 Pareto；BM25-only 不创建 dense manager/index，
  dense-only 不构建 sparse/BM25。
- F-10：打乱 iterators 仍 byte-identical；slug collision 不冲突；conversion unavailable 可复现。

### Process-internal E2E

- 使用 `client` fixture 经 documents route 写入，再由 dense/BM25/hybrid 读取，验证 cache invalidation、filter
  与 disabled channel。
- Fast/Thinking/MCP 双关闭终态一致，`retrieval_diagnostics` 唯一 owner 不变。
- 小 fixture 真实 matrix child 验证 minimal env、独立 store、effective config 和 atomic summary。

### Benchmark

- 现有四数据集运行 8-variant balanced matrix。
- BEIR/Nano-BEIR SciFact/NFCorpus/FiQA；完整小语料优先，FiQA 可单独受资源预算控制。
- MIRACL-zh sampled-local；明确 official false。
- frontier specialized 复跑，synthetic 保持 promotion false。

### UI

无 UI 改动，Playwright 不适用。

## 10. Rollout, Rollback, and Invariants

- 新生产开关默认 true，恢复全 true 即原行为；不迁移/删除生产索引。
- benchmark 不自动更新生产 baseline/default。
- 不新增 `shared_state` 键；request diagnostics 用 core ContextVar，不写 skill 实例。
- filter capability 仍逐 leg fail-closed；disabled 不可成为绕过 filter 的 fallback。
- graph store 路径继续暴露模块级属性，测试可重定向。
- private golden 不外发、不自动生成；它仍是封闭部署最终 promotion gate。
