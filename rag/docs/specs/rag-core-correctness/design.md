# RAG Core Correctness — Design

> v4（2026-07-16）：补齐 strict-msgpack 整数范围、请求边界状态清理、权威 nullable score、
> embedding 实际加载源与版本化 benchmark baseline 的闭环设计。

## Architecture Decisions

### Markdown hierarchy

`_simple_markdown_load` 使用 `heading_stack[level]` 替代单一 `current_parent_id`。处理新标题时先弹出
所有 `level >= current_level` 的节点，再取剩余栈顶作为父标题；随后把当前标题压栈。正文始终挂到当前标题。
既有 `_build_element_tree` 与 `_precompute_links` 无需新增状态即可得到完整 `title_path`。

### Structured evidence contract

新增共享纯函数 `document_to_evidence` / `evidence_to_document` / `prepare_evidence`，证据 wire shape 为：

```text
{
  "content": str,
  "source": str,
  "title": str,
  "score": float | None,
  "metadata": dict[str, JSON/msgpack-safe scalar | list | dict]
}
```

RetrieveSkill 是 `retrieval_evidence` 的唯一生产者，每次 sync/async SUCCESS/PARTIAL/FAILURE 都整键覆盖，
空结果必须写 `[]`，防止 rewrite 或同 thread 下一轮复用旧证据。节点仍输出原 `ToolMessage` 以兼容 grade、
checkpoint 和 API。GenerateSkill 读取该键的三态为：缺失→旧文本兼容；存在且合法（包括空列表）→权威结果；
存在但非法→标记 degraded 并回退旧文本。

`prepare_evidence` 返回基础类型 `PreparedEvidence` dict：`context/evidence/contexts/sources/scores/truncated/degraded`。
它先为 system prompt、question、conversation history 与 generation 预留预算，再按完整 evidence 边界打包；证据文本使用
`<<<RETRIEVED_EVIDENCE>>>` / `<<<END_RETRIEVED_EVIDENCE>>>` 固定定界，source/title/content 中的控制字符与
伪 closing delimiter 被转义。Generate sync/async 的 refusal、LLM、grounding、confidence 和 state updates 全部只消费
PreparedEvidence。Generate 另写 `generation_evidence`（唯一生产者）供 REST sources 使用，不覆盖 retrieve 所有的原始键。
fast sync/async/stream 也调用同一 helper，API sources 与 retrieval_count 只基于 kept evidence。
GradeSkill sync/async 与 per-document grader sync/async 使用共享 `render_untrusted_evidence`，在各自 prompt 中加入
data-only 指令与相同 delimiter 转义；per-doc prompt 移入 profile prompt 单一事实来源。任何 evidence→LLM 消费者
不得直接把原始 content/title/source 插值进未定界 prompt。

metadata sanitizer 递归保留 `None/bool/msgpack 64-bit int/finite float/str/list/dict[str,*]`，其中整数范围为
`[-2^63, 2^64-1]`；tuple 转 list，numpy scalar 转 Python scalar；
丢弃 set/bytes/Path/循环/超深值、非字符串键、`_late_chunk_dense` 等大向量键。最大深度 6、每容器 64 项、字符串
4000 字符；局部丢弃只标记 evidence `degraded=True`，不得使整批或 checkpoint 失败。
同一规范化器同时用于 producer 与 consumer：Generate 收到结构化 evidence 时先生成 strict-msgpack-safe 副本，
metadata 内非法值局部丢弃；缺必需字段或 wire shape 非法时回退旧 `ToolMessage`。Harness 请求边界不接受 caller
覆盖 producer-owned evidence/generation/score/source/memory 键，因此任意对象不会在技能执行前进入 checkpoint；
caller 仅可设置 intent/filter/query-transform/parent-expansion 等请求控制键和独立命名空间扩展键。

### Score semantics

把稳定 sigmoid 提取到 `core/retrieval/scoring.py`，retrieve filter 与 per-doc scoring 共用。每个 signal
表示为 `float | None`：仅 `rerank_score` raw logit 先 sigmoid；合法有限的 `rerank_prob` 原样使用；含义不明的
`relevance_score` 不参与；LLM 仅显式 true/false 产生 1/0，异常/非法为 `None`；当前无生产者的 embedding signal
保持 `None`，未来接入 cosine 时须先从 `[-1,1]` 映射到 `[0,1]`。
融合时仅累计非 `None` 权重。无信号时返回原文档副本并附 `score_degraded=True`，不写 `grade_score`。
仍有信号但全部低于 threshold 时保留最高有效分文档，写真实 fused score，不伪造 0；同批另有不可用信号时，
该真实 top-1 与全部降级文档共同保留。sync/async 共用同一选择 helper。Python `bool` 虽是 `int` 子类，
但不能成为 raw logit；raw logit 统一经 finite-real helper 校验后 sigmoid，布尔、NaN/Inf 与不可转换值均返回 `None`。
`_mean_relevance` 优先 fused `grade_score`，其次合法 `rerank_prob`/sigmoid(logit)；只有 RRF score 时返回 None，
不得把约 0.01 的 RRF 分数冒充概率。sigmoid 只是统一数值域，不宣称统计校准。

REST `SourceDocument.score` 延续原字段并明确为 `float | null`。结构化 evidence 用“键存在性”而非 truthy/值判断：
顶层 `score` 是唯一权威值，显式 `None`/非法值直接输出 `null`，不得回退 rank-only
`metadata.score`。`evidence_to_document` 先移除旧 metadata score，再仅写回合法概率，保证
fast sync/async/stream 不泄漏 RRF 排名分。旧 `ToolMessage` 的
显式有限 Score 文本或 metadata 值仍作兼容。前端类型为 `number | null`，只在 `score != null` 时渲染，并通过
单一 formatter 把 `[0,1]`（闭区间，含 0 与 1）统一显示为百分比；仅 legacy `>1` 有限值保留固定小数显示。

### Request-boundary shared state

`shared_state` reducer 继续保持浅合并不变量，不引入删除 sentinel。Harness 新增唯一纯 helper，先生成所有当前
请求级键的中性值（空 evidence/contexts/sources/memories/history，`None` 分数/过滤器/意图，false fallback），再叠加
调用方本请求的 caller-owned 控制键，producer-owned 键保持中性值，最后在 `history is not None` 时整键覆盖
`conversation_history`。`invoke`、`stream`、
`ainvoke`、`astream` 均只通过该 helper 构造 graph inputs；显式空 history 不得因 truthy 判断被忽略。这样 checkpoint
仍保留消息连续性，但请求 scratchpad 在每轮开头被已知键整键覆盖；即使 agent 直接 END 或在 generate 前失败，API
看到的 `generation_evidence=[]` 也不会回退旧 ToolMessage 来源。新增同 thread 两轮真实 checkpointer 回归，并对四入口
做输入对称性测试。

### Configuration source of truth

`utils.env_utils.resolve_embedding_settings()` 是唯一 effective 配置解析器：显式 env 优先；local 默认
`BAAI/bge-m3`/本地路径/1024；api 默认 `text-embedding-v3`/512；auto 先解析 provider 再选对应默认。
解析结果同时暴露实际 `model_source` 与独立的 `is_bge_m3` capability：仅当 local path 存在模型标记时使用该路径，
否则使用 model id；加载器用 capability 选择模型族、用 `model_source` 定位权重，Milvus schema 与 registry 消费同一
对象。BGE-M3 默认目录只适用于 effective BGE-M3，显式其它 model 且未给 path
时 path 为空、直接加载其 model id；未知 local model 未给 dimension 时 fail fast。native sparse capability 只对
BGE-M3 默认开启，非 BGE-M3 显式开启时报配置错误。registry 的 model identity 使用实际 `model_source`，因此不会
出现“加载 BGE-M3 目录、却登记 custom/other”的向量空间伪一致。`models.embedding_models`、Milvus schema、
admin health、deploy profile 均消费 resolver，不再重复字面默认。
`MilvusConfig` 用 helper 按
`MILVUS_DB_URI -> MILVUS_URI -> ./milvus_data.db` 解析。新增无 secret 的 SHA-1 配置指纹 helper，
canonical payload 带 `schema_version=1`，使用 sorted compact JSON，覆盖 effective profile/provider/model/dimension、
collection、sparse/reranker model+enabled、graph、late-chunk 开关；由 admin health 和启动日志复用，不输出 URI、
API key 或本地绝对路径。

启动/health 读取 embedding registry 的 effective model fingerprint、实际 dense dimension 与 sparse capability；任一
不兼容时设置 degraded 并禁止 query/write，绝不把相同维度误当作相同向量空间。提供离线迁移命令：按 resolver 的
effective provider/model source/dimension/sparse target 从 registry/parent source 重建到显式新 collection。迁移前比较
document registry 的全部 indexed filename 与 parent_store source，缺任一 source 即停止；写入后校验文档数、
目标 schema 与至少一个 sample query 的非零召回，任一 0-hit 删除 target。CLI 默认要求 sample query，只有显式
`--skip-recall-check` 风险确认可绕过召回门禁。验证后由运维切换 `COLLECTION_NAME`；不得硬编码 1024 或 sparse。旧 collection 在观察期保留；
回滚同时恢复旧 collection 与对应 embedding 显式配置。本阶段不自动 drop 或原地改写已有 collection。

### Graph schema migration

relations 表目标主键为 `PRIMARY KEY (id, source)`，`PRAGMA user_version=2`。新库直接创建 v2；旧库初始化时
使用显式 `BEGIN IMMEDIATE` 取得 DB 写锁后再次检查 schema，逐条 `execute` 创建临时表、复制、校验行数、
删除旧表、rename、重建索引并更新 user_version，禁止迁移内 `executescript`。异常显式 rollback、关闭 connection
并 re-raise，singleton 不缓存半初始化对象。Relation 的逻辑 id
保持不含 source，source 作为复合主键第二列，避免破坏图算法引用。upsert 使用冲突目标 `(id, source)`。
同 source 重复 relation 更新 description/weight。迁移异常由 GraphStore 抛出，摄入/检索现有上层捕获后按
GraphRAG degraded-empty 处理。

部署迁移前暂停 graph 写入并用 SQLite backup API 创建模块级可重定向 v1 备份；迁移验证后恢复能力。旧代码回滚
必须停服务并恢复 v1 备份，观察期内 v2 新增 graph 写入会丢失；不能接受该窗口数据丢失时只允许前滚修复。

## Data Flow

```text
Markdown heading stack -> child Documents -> hybrid retrieval/rerank
    -> RetrieveSkill filters/scores
    -> retrieval_evidence (structured) + ToolMessage (compat)
    -> prepare_evidence (thinking + fast shared)
    -> generation_evidence + kept contexts/sources/scores
    -> generation + grounding/confidence
```

## Invariants and Failure Modes

- `retrieval_evidence` 只含可 checkpoint 的基础类型，禁止 `Document`、Pydantic 或 numpy 值。
- `generation_evidence` 是 GenerateSkill 的 kept-set，API 只从它构建 sources；两键所有权不得互换。
- 结构化路径失败回退旧文本路径；不可用信号为 `None`，永不当作 0。
- `ToolMessage`、REST schema、既有 shared-state 键保持兼容。
- graph schema migration 使用数据库级写锁、单事务、可重复执行；旧库复制失败不允许半迁移。
- 配置指纹仅用于观测，不参与缓存键或业务路由。
- SQLite singleton 构造器参数默认 `None`，函数体从当前模块级 `DEFAULT_DB_PATH` 解析，保证测试重定向生效。
- benchmark 在 `finally` 中只关闭本进程创建的 hybrid retriever、其 dense manager、摄入 manager 与 embedding registry；关闭必须幂等，正常/异常路径均不得因非 daemon executor 或 SQLite/Milvus 连接残留而挂起。

## Test Matrix

| Layer | Cases |
|---|---|
| Unit | 标题升降/跳级；evidence 三态、递归 sanitizer 与 strict-msgpack 64-bit 整数；generate/binary-grade/per-doc-grade prompt injection golden；raw/prob/bool/NaN/缺失及 mixed signal；nullable/真实零分/RRF 非概率来源；provider/URI/fingerprint；graph v1→v2 migration 与跨 source 删除 |
| In-process E2E | retrieve→generate sync/async 只用 kept evidence；兼容 ToolMessage；REST sources 与 prompt 一致；恶意文档定界 |
| Fast | sync/async/stream 共用 packer，均不截半证据且只返回 kept sources |
| Checkpoint | `retrieval_evidence` 经 sync/async strict msgpack SQLite round-trip；超界正/负整数被丢弃并标 degraded；同 thread 两轮请求态不串扰 |
| Migration | 同维不同 model fingerprint、维度或 sparse capability 不匹配均被阻断；local/API effective target 新 collection 重建；indexed source 缺失/zero-hit sample 删除 target；graph 双 connection 并发迁移/注错 rollback/reopen |
| Degradation | evidence 非法局部丢弃；全部 score signal 不可用不产生 0；graph migration 失败不阻断主路径 |
| Regression | mixed reranker 保留 best-valid + unavailable；REST/fast 不泄漏 RRF score；tracked baseline 缺失/错配 fail closed；现有 unit/e2e/perf、真实检索 benchmark、Playwright |

真实检索 benchmark 使用隔离 Milvus/registry 路径与同模型、同参数重复运行，CLI 默认三轮并允许显式覆盖。
每轮保留逐查询延迟和质量指标；质量报告使用 hit/precision/recall 的中位数与最差值，回归门禁读取最差值；
性能把所有轮次按执行顺序合并，仅排除全局第一个冷查询后报告 P50/P95。规则
`answer_overlap` 只衡量 top-1 文本字符覆盖，受近似索引同分排序影响，仅作 advisory，不作为回答质量或回归门禁。

benchmark baseline 从忽略的 runtime runs 迁移到 `data/benchmark/baselines/` 并进入版本控制。baseline schema
固定包含 `schema_version`、质量语义版本、dataset/corpus SHA-256、dataset stem、
`n_cases/top_k/dedup_source/repeats`、不含 secret/绝对路径的 effective embedding
`provider/model/dimension/sparse` identity 与门禁指标；读取时逐项验证类型、有限性、`[0,1]` 范围和当前运行配置。
`--fail-on-regression` 遇到缺失/陈旧/错配基线返回非零，绝不自动写文件；它与 `--update-baseline` 互斥，只有维护者
显式 update 才以临时文件 + 原子 replace 生成候选 diff。旧单轮 baseline 不直接换壳，必须以相同模型、隔离存储和
三轮语义重新测量后提交。CI 固定与 tracked baseline 相同的 embedding 配置，并用 `uv run --frozen` 执行。

## Rollback

- Evidence 路径没有运行时 feature flag；异常发布通过版本回退处理。旧消息路径与新增 shared-state 键保持前后兼容，
  回退前必须用旧版本读取含新键 checkpoint 做兼容演练。2026-07-16 已完成隔离演练：实现提交写入含新 evidence
  键与 legacy `ToolMessage` 的 checkpoint，`origin/main@45d68f0` 成功读取并继续 graph invoke。
- embedding/Milvus 回滚使用显式 BGE-small/512 + 旧 collection，禁止只回滚其中一项。
- graph v2 回滚按 backup 流程恢复 v1 DB；默认关闭 GraphRAG 只停止能力，不能替代 schema 恢复。

## Security Impact

- Evidence metadata 仅允许 sanitizer 后的基础类型。prompt 单一事实来源明确 evidence 为不可信数据，renderer
  转义控制字符与 closing delimiter，新增间接提示注入 golden。
- 配置指纹禁止包含 secret、URI 和绝对路径。
- schema migration 使用固定 SQL 标识符，source 仅参数绑定，不引入注入面。
