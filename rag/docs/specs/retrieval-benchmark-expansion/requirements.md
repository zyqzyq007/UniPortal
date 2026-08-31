# Retrieval Benchmark Expansion — Requirements

## 1. Surface Requirement

用户需要在封闭部署、小样本和个人使用场景下，确认 retrieval-frontier 的收益不是由单一数据集、
单一检索组合或实验顺序造成，并在合并前获得可复现的质量、延迟与资源对比。

## 2. Essential Requirement

本质需求不是继续堆叠公开榜单，而是建立一套可在本机、离线缓存和有限算力下重复运行的实验协议：
同一语料、同一模型、隔离存储下比较单通道、混合、重排和统一 workflow；公开数据只用于补足中文、
科学、金融、医疗与多跳分布，私域能力最终仍由用户自己的 golden 决定。

## 3. Scope

### In Scope

- 多 baseline 命名矩阵与前后序隔离执行。
- Dense-only、BM25-only、Hybrid RRF、Hybrid+Reranker、Workflow、候选漏斗和 contextual 消融。
- 通用 `ir_datasets` 适配，覆盖 Nano-BEIR/BEIR 与 MIRACL-zh。
- 完整语料和 `qrels-plus-negatives` 小样本两种模式，并显式区分是否可与官方分数比较。
- 质量、延迟、资源、降级和查询前向次数的统一结果。
- 私域 golden 接入说明；不得伪造用户私有问题或答案。

### Out of Scope

- 训练或微调 embedding、reranker、LLM 权重。
- 把抽样语料结果宣称为公开榜单成绩。
- 在运行期自动下载 ColPali/ColBERT 模型。
- 没有真实页面模型和资产时，把 synthetic visual benchmark 当作上线证据。
- 生成用户私域 golden；这需要用户拥有的文档、问题和人工相关性标注。

## 4. Functional Requirements

- **REQ-RBE-001**: WHEN benchmark matrix 配置被加载时, THE SYSTEM SHALL 只接受唯一、安全命名的
  variant 和显式 allowlist 中的检索环境键，拒绝 secret、未知键和 shell 内容。
- **REQ-RBE-002**: WHEN 任一 variant 运行时, THE SYSTEM SHALL 使用独立进程、Milvus、collection、
  embedding registry、RAPTOR、visual assets 和 cache namespace。
- **REQ-RBE-003**: WHEN 运行 quick smoke 时, THE SYSTEM SHALL 使用前序/反序；WHEN 结果用于最终性能或
  promotion 判断时, THE SYSTEM SHALL 使用 balanced schedule，使每个 variant 在每个调度位置出现相同
  次数，并分别验证质量顺序漂移与延迟位置效应。
- **REQ-RBE-004**: WHEN 未配置新通道开关时, THE SYSTEM SHALL 保持 dense 与 sparse 通道默认开启，
  与当前兼容行为一致。
- **REQ-RBE-005**: WHEN `RETRIEVAL_DENSE_ENABLED=false` 时, THE SYSTEM SHALL 在正常路径、query
  representation、planner、retry 和所有异常 fallback 中均不执行 dense leg；WHEN
  `RETRIEVAL_SPARSE_ENABLED=false` 时, THE SYSTEM SHALL 同样不执行 native sparse 或 BM25 leg。
- **REQ-RBE-006**: WHEN dense 与 sparse 均关闭且没有可用可选通道时, THE SYSTEM SHALL 安全返回空证据
  和 degraded diagnostics，绝不抛出热路径异常，也不得把“不可用”记录为 0 分。
- **REQ-RBE-007**: WHEN active channel、backend、权重、预算、后处理、模型或索引 generation 改变时,
  THE SYSTEM SHALL 将 canonical retrieval identity 纳入 cache key；cache hit diagnostics SHALL 区分
  `disabled`、`cache_hit` 与 `unavailable_or_no_match`，禁止跨 variant 复用结果。
- **REQ-RBE-008**: WHEN matrix 完成时, THE SYSTEM SHALL 以指定 reference variant 输出每个数据集的
  Recall、Precision、MRR、nDCG、first-query/P50/P95、吞吐量、摄入/索引时间、store bytes、RSS、
  GPU allocated/reserved、query-forward 与 subprocess wall-time 差值；不可用资源值 SHALL 为 `None`
  并附原因，永不当作 0。
- **REQ-RBE-009**: WHEN 多个 variant 存在质量/延迟取舍时, THE SYSTEM SHALL 输出非支配 Pareto 集，
  但不得仅凭单一综合分自动修改生产默认值。
- **REQ-RBE-010**: WHEN `ir_datasets` 数据集被转换时, THE SYSTEM SHALL 保留 query id、stable doc id、
  完整 graded qrels、标题和正文，并生成 versioned public-IR scorer 产物及与现有 harness 兼容的 YAML。
- **REQ-RBE-011**: WHEN 采用 `full` corpus mode 时, THE SYSTEM SHALL 摄入完整语料；仅在完整标准 query
  集、完整 graded qrels、标准 split、逐数据集 allowlist cutoff、无 dedup/limit 且 public evaluator 版本
  匹配时，结果才可标记 `official_comparable=true`；否则最多标记 `harness_comparable=true`。
- **REQ-RBE-012**: WHEN 采用 `qrels-plus-negatives` corpus mode 时, THE SYSTEM SHALL 包含所有所选 query
  的正相关文档和确定性 hash 采样负例，并强制标记 `official_comparable=false`。
- **REQ-RBE-013**: WHEN 数据源缺失、网络不可用或 dataset adapter 失败时, THE SYSTEM SHALL 在原子
  `conversion_summary.json` 中给出稳定 unavailable/error code 并保留其他数据集产物，绝不生成空文件
  冒充成功数据集。
- **REQ-RBE-014**: WHEN 写出公开数据产物时, THE SYSTEM SHALL 记录 dataset id、split、corpus mode、
  query/doc 限制、seed、source fingerprint 和许可/来源提示。
- **REQ-RBE-015**: WHEN 输出路径或 dataset id 参与文件命名时, THE SYSTEM SHALL 使用可读 slug + dataset
  id hash；一个 dataset 的 cases/corpus/qrels/manifest SHALL 作为 generation bundle 原子发布，已有 ready
  generation 默认保留，除非新 generation 完整校验后显式切换 pointer。
- **REQ-RBE-016**: WHEN benchmark 运行时, THE SYSTEM SHALL 使用去 secret 的最小 child environment，
  强制 local embedding/reranker、禁用 LLM/judge/API fallback 和运行期模型下载；本地依赖或 checkpoint
  缺失时 SHALL 在启动任何子进程前标记 unavailable。
- **REQ-RBE-017**: WHEN private-domain golden 被接入时, THE SYSTEM SHALL 复用现有 `cases` + `chunks`
  契约和隔离 runner，不要求上传到第三方服务。
- **REQ-RBE-018**: WHEN visual frontier 没有真实 ColPali dependency/checkpoint 时, THE SYSTEM SHALL 继续
  报告 `promotion_eligible=false`，不得把 OCR 或 synthetic encoder 结果冒充真实视觉模型结果。
- **REQ-RBE-019**: WHEN benchmark 超过 variants/datasets/repeats、query/doc/corpus bytes、候选预算、
  最小空闲磁盘、单 run/总 wall-time 或输出 bytes 任一上限时, THE SYSTEM SHALL 在创建子进程或目标产物前
  fail-closed；超时 SHALL 终止整个子进程组并原子记录失败。
- **REQ-RBE-020**: WHEN 本功能交付时, THE SYSTEM SHALL 提供单元测试、进程内 E2E、红绿证据、完整矩阵
  结果、benchmark 命令、回滚方式和默认值决策。

## 5. Non-functional Requirements

- **REQ-RBE-021**: THE SYSTEM SHALL 使用 JSON/YAML 可审计产物，禁止 NaN/Infinity 和 secret，并记录
  requested/effective config、依赖/硬件、tracked diff、相关 untracked 文件、数据/模型 revision fingerprint。
- **REQ-RBE-022**: THE SYSTEM SHALL 对相同输入、seed、模型和工作树产生相同 query/doc 选择与资源身份。
- **REQ-RBE-023**: THE SYSTEM SHALL 将下载缓存与运行产物置于显式目录；默认 benchmark 结果写入 `/tmp`
  或用户指定目录，不污染运行时数据库。
- **REQ-RBE-024**: THE SYSTEM SHALL 保持所有新增生产开关默认兼容，并允许显式关闭 matrix/adapter 功能
  而不迁移或删除现有索引。

## 6. Acceptance Criteria

- 当前 unit + process-internal E2E 全绿。
- named matrix 在至少 4 个已有数据集完成 balanced schedule 实验。
- BEIR/Nano-BEIR SciFact/NFCorpus/FiQA 与 MIRACL-zh 小样本至少成功转换和校验；若外部下载不可用，必须有
  可重复的 unavailable 证据，不能伪造结果。
- Dense-only/BM25-only 与 hybrid/workflow baseline 的通道计数证明未执行被关闭 leg。
- 结果报告明确区分 `official-comparable`、`full-local`、`sampled-local`、`synthetic` 四类证据。
