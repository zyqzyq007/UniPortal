# Defender Preliminary — retrieval-benchmark-expansion

**评审日期**: 2026-07-16
**评审对象**: `requirements.md` / `design.md` / `tasks.md` v1
**独立性声明**: 本报告在未读取 critic 报告的前提下完成，只核验设计事实、现有可达路径和诚实边界；
不是对 critic finding 的最终裁决。

## Preliminary Verdict

总体方向可辩护：冷路径 matrix、独立进程/存储、默认兼容的 dense/sparse 开关、公开 sampled 结果不作
promotion，以及私域 golden 优先，均符合封闭部署和小样本场景。但 design v1 尚不能直接进入编码；以下
High 项若不先收紧，会出现“关闭通道仍被调用”“公开分数被过度解释”或“doc id 评分错误”。

## 可辩护的既有基础

1. 现有 `run_paired_benchmark.py:119-176,183-218,313-371` 已提供独立进程规格、独立 Milvus/
   collection/embedding registry/RAPTOR/visual/cache namespace、输入快照校验和失败关闭，可作为 matrix
   runner 的基础，而不是重写另一套隔离器。
2. 现有 retrieval cache 已有 namespace 与 index version：`core/retrieval/cache.py:97-141`；把通道身份加入
   `HybridRetriever._cache_key_for()` 是小而明确的增量，不需要新持久化 schema 或 `shared_state` 键。
3. 本机锁定环境的 `ir_datasets==0.6.1` 实际注册了 `nano-beir/scifact`、`nano-beir/nfcorpus`、
   `nano-beir/fiqa` 和 `miracl/zh/dev`。核验到 corpus 数分别为 2,919、2,953、4,598、4,934,368，
   因此 Nano-BEIR full 可行，MIRACL-zh 必须按大语料下载/扫描边界处理。
4. 私域继续复用 `cases + chunks` 是合理最小接口：`agent/eval/types.py:21-46` 与
   `agent/eval/dataset.py:24-38` 已支持 query、reference answer 和 expected context ids，且不要求外传数据。
5. visual 边界表述诚实：`scripts/run_frontier_benchmark.py:262-273` 已明确
   `synthetic_encoder=true`、`promotion_eligible=false`，design v1 没有把 synthetic 结果冒充真实 ColPali。

## 编码前必须处理的风险

### DP-01 — High — `official_comparable` 条件不充分

- **事实**: design v1 §1 仅以 `full + unlimited + standard split` 判定可比；现有 `EvalCase` 只保存二值
  `expected_context_ids`（`agent/eval/types.py:21-46`），`run_benchmark.py:228-241` 也用二值 gain 计算 MRR/
  nDCG，并由任意 `--top-k` 决定 cutoff。BEIR/MIRACL 的官方协议还要求固定 cutoff、完整 qrels relevance
  grade、官方 query 集及一致的 metric 定义。
- **可触发性**: 即使完整转换 Nano-BEIR，默认 matrix 的 `top_k=4`（design v1 §6）也不能宣称与常见
  nDCG@10/Recall@100 官方结果同协议。
- **要求**: v2 应把 `official_comparable` 默认设为 false；只有 IR-native scorer 保留 qrel grade、显式记录
  `metric@cutoff`，且 dataset/split/query/corpus 全量并命中逐数据集协议 allowlist 时才可为 true。否则使用
  `harness_comparable=true` 或 `evidence_class=full-local`，只与本仓库同协议结果比较。

### DP-02 — High — 当前 sidecar 路径不能可靠保留公开数据的 doc id

- **事实**: adapter 计划保留 doc id，但 `run_benchmark.py:171-176` 在检索结果无 `chunk_id` 时退回正文反查；
  Milvus 搜索默认额外输出字段不含 `chunk_id`（`documents/milvus_db.py:111-130`），而写入正文会截断到
  4,000 字符（`documents/milvus_db.py:641-647`）。重复正文或长正文会被映射到错误 id/内容 hash。
- **可触发性**: Nano-BEIR/MIRACL 是真实公开语料，不能假定正文唯一且小于 4,000 字符。
- **要求**: v2 必须规定 stable `doc_id/chunk_id` 作为检索输出字段并直接评分，不以正文作为公开 benchmark
  身份。测试至少覆盖重复正文、超过 4,000 字符正文和 graded qrel。更稳妥的方案是 IR adapter/runner
  使用独立的 ranked `(query_id, doc_id)` scorer，YAML 仅保留现有 harness 兼容层。

### DP-03 — High — 七 variant 的 forward/reverse 不能满足位置独立性

- **事实**: REQ-RBE-003 要求每个 variant 出现在不同调度位置；design v1 默认 7 个 variant 且只有
  forward/reverse。奇数列表的中间 variant 在两种顺序中都处于第 4 位。
- **要求**: 保留 forward/reverse，同时为奇数矩阵增加 deterministic rotation（或使用平衡 Latin/Williams
  schedule），并让 order-independence 按每个 variant 的全部 order 比较。相应更新 `12×12×2` 的资源上限。

### DP-04 — High — 通道关闭必须覆盖异常 fallback，而不只是正常 leg 创建

- **事实**: 当前同步热路径在任意外层异常后无条件尝试 dense fallback：
  `core/retrieval/hybrid_retriever.py:563-570`。若只在正常同步/异步/parallel 分支加入 `enable_dense`，
  `RETRIEVAL_DENSE_ENABLED=false` 仍可能执行 dense。
- **要求**: v2 明确开关约束适用于正常路径、representation、fallback、retry 和 workflow optional fusion；
  disabled channel 永不作为降级目标。红测试必须主动触发 RRF/rerank 异常并断言 dense/sparse call count 为 0。

### DP-05 — High — 子进程隔离与离线契约仍不完整

- **事实**: 复用基础 runner 时，`run_paired_benchmark.py:328-338` 从 `os.environ.copy()` 启动，因此会继承
  API key/provider/network 配置；现有隔离集合也没有 graph store。`documents/graph_store.py:54` 使用固定
  `./data/graph_store.db`，而 paired 默认环境没有强制 `GRAPH_RAG_ENABLED=false`。此外 `shell=False` 虽是
  `subprocess.run` 的默认值，但 design 应显式传入并测试。
- **要求**: matrix 必须构造最小化、去 secret 的子进程环境，显式设置本地 provider 与
  `HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE`，模型未缓存时标 unavailable 而不是调用 API/下载；默认矩阵强制
  所有未比较的 optional channels 关闭。若允许 graph variant，则先增加可注入的 graph store 路径并隔离；
  否则明确拒绝 graph 开关。不得仅依赖 variant allowlist 来推导“子进程没有 secret”。

### DP-06 — High — 三文件逐个 `os.replace` 不是 bundle atomic

- **事实**: design v1 §2.3 同时发布 cases YAML、corpus YAML 和 metadata JSON，却只描述同目录 staging 后
  逐个 `os.replace`。第二或第三次替换时进程中断会留下半套产物；`--overwrite` 时还可能混合新旧版本。
- **要求**: 每个 dataset 写入独立 staging 目录，完整校验后原子发布整个 bundle 目录；或以 manifest-last
  作为 commit marker，并确保消费者拒绝无 manifest/指纹不一致的半成品。回归测试需覆盖中途失败和
  overwrite 回滚。

### DP-07 — Medium — `ir_datasets` 依赖与缓存边界需显式化

- **事实**: `pyproject.toml:11-53` 的基础依赖没有 `ir-datasets`；它当前只是
  `flagembedding`（`local-models` extra）的传递依赖。API-only/bare sync 不能据此承诺 adapter 可运行。
  `ir_datasets` 默认缓存是 `~/.ir_datasets`，而 design CLI 没有 `--cache-dir`。MIRACL-zh sampled 虽只输出
  2,000 negatives，确定性全局最小 hash 仍需扫描/获取 4,934,368 篇 corpus。
- **要求**: 用 `uv` 声明可复现的 benchmark dependency profile（或直接依赖），增加显式 cache dir/
  `IR_DATASETS_HOME`、预估 counts/磁盘提示和 `--offline`；报告应区分“输出样本小”与“源语料下载/扫描大”。
  网络或缓存不足可记 unavailable，不应成为虚假成功或阻断其他 dataset。

### DP-08 — Medium — baseline 名称需要与实际 post-processing 一致

- **事实**: 当前 `HybridRetrieverConfig.enable_mmr` 默认 true（`hybrid_retriever.py:108-112`），time-decay
  也默认运行（`hybrid_retriever.py:528-541,1087-1089`）；reranker 开关还会改变默认 candidate pool
  (`hybrid_retriever.py:91-105`)。因此 `dense_only`/`bm25_only`/`hybrid_rrf` 并非天然代表纯算法基线。
- **要求**: v2 要么固定所有 variant 的 candidate/rerank/selection/final budget 并提供 MMR/time-decay 开关，
  要么将名称改为 `dense_leg_pipeline`、`sparse_leg_pipeline`、`hybrid_no_reranker`，在 summary 输出完整 stage
  fingerprint。否则 delta 不能归因于单一组件。

### DP-09 — Medium — worktree fingerprint 不能遗漏未跟踪实现

- **事实**: `run_paired_benchmark.py:221-231` 只 hash `HEAD + git diff`；`git diff` 不包含 untracked 文件。
  当前 retrieval-frontier 的多个实现/脚本正是 untracked，预合并 benchmark 会产生不完整 provenance。
- **要求**: matrix fingerprint 应包含 porcelain 状态与所有相关 untracked 文件 hash，或规定最终 promotion
  benchmark 只能在已提交且 clean 的 feature commit 上运行。推荐两者都做：开发期完整脏树 fingerprint，
  promotion 期要求 clean commit。

## 诚实承认的有限边界

- Nano-BEIR full 只证明公开小型分布上的本地检索能力；不能替代用户封闭领域的人工 qrels golden。
- MIRACL-zh `qrels-plus-negatives` 是本地消融，不是 MIRACL 官方成绩；小输出不代表小下载。
- 没有真实 ColPali checkpoint、页面资产和 ViDoRe 协议时，visual 结果只能验证接线/降级。
- 模型配置 fingerprint 通常是模型名/路径/维度身份，不等同于对数 GB checkpoint 的内容证明；报告应说明
  fingerprint 强度，并优先记录 revision/manifest hash。
- Pareto 集只展示取舍，不应自动修改生产默认值；私域 golden 仍是最终 promotion gate。

## Preliminary Gate

在 DP-01～DP-06 进入 design v2 且对应测试任务落入 `tasks.md` 前，不建议开始实现；DP-07～DP-09 可与
实现一起闭环，但必须在最终 benchmark 前完成。最终 defender 将在收到 critic findings 后逐条走 5 步
决策树并形成正式 `defender.md`。
