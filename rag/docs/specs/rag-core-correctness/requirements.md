# RAG Core Correctness — Requirements

## Problem Statement

当前 RAG 核心已有层级切分、small-to-big、混合检索、reranker、逐文档评分与 GraphRAG，
但基础正确性与可审计性仍存在缺口：Markdown 父链、跨节点结构化证据、分数标尺、请求态隔离、
embedding 实际身份、collection 迁移、Graph relation 跨来源主键及 benchmark 回归契约可能发生漂移。
本阶段闭合这些基础问题，不引入自适应路由或 community GraphRAG。

## Requirements

### Markdown hierarchy

- **REQ-RCC-001**: WHEN Markdown 标题级别发生升降或跳级，THE SYSTEM SHALL 使用标题栈恢复最近的合法父标题，并为每个 section 生成正确的完整 `title_path`。
- **REQ-RCC-002**: WHEN 文档包含标题前正文、同级标题或空 section，THE SYSTEM SHALL 保持原有内容顺序且不得把正文挂到前一个无关 section。

### Structured evidence

- **REQ-RCC-003**: WHEN retrieve 节点产出文档，THE SYSTEM SHALL 在 `shared_state["retrieval_evidence"]` 写入 strict-msgpack 可序列化的 `list[dict]`，每项至少包含 `content/source/title/score/metadata`；metadata 整数必须落在 msgpack 可编码的 `[-2^63, 2^64-1]`，越界值局部丢弃并标记 degraded。
- **REQ-RCC-003A**: WHEN caller、旧 checkpoint 或扩展组件提供结构化 evidence，THE SYSTEM SHALL 在写入 checkpoint 或交给 generate 前按同一有界递归 allowlist 重新规范化；非法 metadata 项局部丢弃并标记 degraded，结构本身非法时安全清空或回退旧文本路径，不得让 strict-msgpack 异常逃出热路径。
- **REQ-RCC-004**: WHILE 旧 graph、MCP 与 API 仍消费 `ToolMessage`，THE SYSTEM SHALL 保留现有格式化文本输出及既有 `retrieved_contexts`/`sources` 契约。
- **REQ-RCC-005**: WHEN generate 节点收到结构化证据，THE SYSTEM SHALL 优先从该结构构建 token-budget context；WHEN 结构化证据不存在，THE SYSTEM SHALL 回退现有消息文本路径。
- **REQ-RCC-006**: WHEN token budget 丢弃证据，THE SYSTEM SHALL 同步裁剪用于 grounding、来源和相关性计算的证据集合，避免未喂给模型的文档进入置信度或引用。
- **REQ-RCC-006A**: WHEN fast sync/async/stream 生成回答，THE SYSTEM SHALL 复用与 thinking mode 相同的 evidence 转换、边界感知 token packing 与 kept-source 契约。
- **REQ-RCC-006B**: WHEN evidence 被渲染进 prompt，THE SYSTEM SHALL 使用不可逃逸的数据定界，并明确要求模型忽略 evidence 内任何指令。
- **REQ-RCC-006C**: WHEN binary grade 或 per-document grade 消费检索文本，THE SYSTEM SHALL 复用同一不可信数据 renderer 与 data-only 指令，sync/async 路径不得直接插值原文。

### Score calibration

- **REQ-RCC-007**: WHEN per-document scoring 消费 cross-encoder raw logit，THE SYSTEM SHALL 使用与 retrieve filter 相同的数值稳定 sigmoid 转换，不得直接 clamp raw logit。
- **REQ-RCC-008**: WHEN LLM grade、reranker 或 embedding signal 不可用，THE SYSTEM SHALL 用 `None` 表示不可用并只对存活信号重新归一化权重，不得注入 0 或 0.5 伪分数。
- **REQ-RCC-009**: WHEN 所有逐文档信号均不可用，THE SYSTEM SHALL 保留原顺序并标记 `score_degraded=True`，不得产生 `grade_score=0`。
- **REQ-RCC-009A**: WHEN 同一批文档同时包含低于阈值的有效分数与不可用分数，THE SYSTEM SHALL 保留真实最高分文档及不可用文档并标记后者降级，sync/async 路径语义一致；WHEN raw reranker logit 是布尔、非有限或不可转换值，THE SYSTEM SHALL 将其视为 `None`。
- **REQ-RCC-009B**: WHEN REST 来源分数不可用，THE SYSTEM SHALL 输出 `score=null` 且前端不显示相关度；WHEN 分数真实为 `0.0` 或 `1.0`，THE SYSTEM SHALL 保留并按概率百分比显示，不得用 truthy 判断隐藏或伪造分数。结构化 evidence 的顶层 `score` SHALL 是唯一权威相关度（包括显式 `null`），不得回退 `metadata.score`；RRF `metadata.score`/`retrieval_score` 不得进入 thinking 或 fast sync/async/stream 的相关度。旧 `ToolMessage` 仅保留其独立兼容解析路径。

### Configuration consistency

- **REQ-RCC-010**: WHEN 未设置 embedding 环境变量，THE SYSTEM SHALL 按 effective provider 解析默认值：local 使用 BGE-M3/项目本地路径/1024 维，API 使用 DashScope `text-embedding-v3`/512 维；用户显式配置始终优先。
- **REQ-RCC-010A**: WHEN 用户显式选择非默认 local embedding model，THE SYSTEM SHALL NOT 复用 BGE-M3 默认目录或默认启用 sparse；未知模型未显式给出维度时 SHALL fail fast，非 BGE-M3 模型显式启用 native sparse 时 SHALL fail fast。模型加载、Milvus schema 与 registry SHALL 消费同一 effective `model_source/dimension/sparse` 配置，registry SHALL 标识实际加载的 model source。
- **REQ-RCC-011**: WHEN 构造 `MilvusConfig`，THE SYSTEM SHALL 优先读取 `MILVUS_DB_URI`，并兼容旧 `MILVUS_URI`；若两者同时存在，以 `MILVUS_DB_URI` 为准。
- **REQ-RCC-012**: WHEN 服务报告健康或启动信息，THE SYSTEM SHALL 暴露不含 secret 的配置指纹，覆盖 profile、embedding model/dimension/provider、collection 与检索关键开关。
- **REQ-RCC-012A**: WHEN effective embedding model fingerprint、dimension 或 sparse capability 与已有 Milvus collection 任一不兼容，THE SYSTEM SHALL 阻止查询/写入并报告 degraded；迁移必须按 effective target 写入新 collection，校验 indexed source 覆盖、完整写入、目标兼容性及至少一个非零命中 sample query 后才能声明成功，任一门禁失败删除 target；只有显式风险确认参数可跳过召回检查，旧 collection 保留用于回滚。
### Graph relation identity

- **REQ-RCC-013**: WHEN 两个 source 抽取相同实体关系，THE SYSTEM SHALL 各自持久化且互不覆盖；删除一个 source 不得删除另一个 source 的关系。
- **REQ-RCC-014**: WHEN 读取旧 graph DB，THE SYSTEM SHALL 通过显式 schema migration 把 relation 主键升级为 `(id, source)`，迁移失败时 GraphRAG 降级为空且不得阻断主摄入/检索。

### Quality gates

- **REQ-RCC-015**: THE test suite SHALL 包含单元、进程内 E2E、strict checkpoint round-trip、热路径降级与配置兼容用例，测试仅位于 `tests/`。
- **REQ-RCC-015A**: WHEN tests 或 hermetic runtime 修改持久化模块的 `DEFAULT_DB_PATH`，THE singleton getter SHALL 在构造时读取修改后的路径，不得使用函数定义时绑定的真实 `./data/` 路径。
- **REQ-RCC-016**: THE implementation SHALL NOT 删除或重命名现有 REST 字段、`ToolMessage` 文本格式或既有 `shared_state` 键；`SourceDocument.score` 保持原字段但明确为 nullable。
- **REQ-RCC-017**: WHEN 真实检索 benchmark 完成或失败，THE runner SHALL 关闭其创建的 retriever、Milvus 与 registry 资源并在有限时间内退出；WHEN 报告性能，THE runner SHALL 输出逐查询延迟及排除首次冷查询后的 warm P50/P95；WHEN 未显式覆盖重复次数，THE runner SHALL 执行三轮并输出 hit/precision/recall 的最差值与中位数，回归门禁使用最差值，`answer_overlap` 仅作 advisory。
- **REQ-RCC-017A**: WHEN benchmark 以 `--fail-on-regression` 运行，THE runner SHALL 从版本控制中的 baseline 目录读取带 schema/config 的基线；基线缺失、schema 不合法、dataset/corpus digest、case-count/top-k/dedup/repeats、effective embedding identity 任一不匹配或指标非有限时 SHALL fail closed，禁止在门禁路径自动播种基线。仅显式 `--update-baseline` 可原子更新基线，且不得与 regression gate 同时启用。
- **REQ-RCC-018**: WHEN 同一 checkpoint thread 开始新请求，THE harness SHALL 在 sync invoke/stream 与 async invoke/stream 的输入边界显式覆盖所有请求级 `shared_state` 键为空值，再叠加本请求参数；显式空 history SHALL 清除旧 history。即使本轮在 generate 前结束，旧 `generation_evidence`、`retrieval_evidence`、`relevant_memories`、`conversation_history`、分数与来源也不得被本轮 API/guardrail 消费。

## Out of Scope

- 自适应 query router、动态 Top-K/RRF 权重、候选池扩容。
- 256/384/512 token 切分消融与默认值切换。
- Graph community/global search、超过 1-hop 的遍历。
- 公共 API breaking cleanup；旧兼容契约的删除另立迁移阶段。
