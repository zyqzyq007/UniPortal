# Defender 报告 — retrieval-frontier-optimization

**评审对象**: `docs/specs/retrieval-frontier-optimization/review/critic.md`
**评审日期**: 2026-07-16

## 裁决表

| 发现 ID | 严重性 | 决策 | 理由 | design.md 修订条目 |
|---|---|---|---|---|
| F-01 | Critical | `accepted` | 所有检索分支必须保留 filter；无法执行时排除通道，禁止返回未过滤结果 | v2 §3.5 |
| F-02 | High | `accepted` | MCP/Fast/Thinking 复用统一 workflow；明确三类终态与 diagnostics 唯一 owner | v2 §4.1/§4.4 |
| F-03 | High | `defended-with-alternative` | 成功路径一次前向；原子失败整批转安全 legacy；缓存键加入完整 fingerprint | v2 §3.2/§6 |
| F-04 | High | `accepted` | 资产覆盖完整页面、稳定唯一命名，并具备创建、替换、清理生命周期 | v2 §5.4 |
| F-05 | Critical | `accepted` | RAPTOR 按 generation 构建，以源版本校验 freshness，并事务原子发布 | v2 §5.2 |
| F-06 | High | `accepted` | benchmark 使用 dataset×variant 独立存储/进程并记录资源身份 | v2 §8.1 |

## 逐条论证

### F-01 — Filter fail-open

- **步骤 1 核验**: 成立。`core/retrieval/hybrid_retriever.py:377-384` 同步 fallback 丢失
  `filter_expr`；legacy BM25 分支不消费 filter；`core/retrieval/graph_retriever.py:474-501`
  解析失败后放行。
- **步骤 2 触发**: 常规同步调用、BM25 分支或 graph 不支持的复合 filter 即可触发。
- **步骤 3 成本**: 统一 typed capability 与降级语义的成本低于越界召回风险。
- **步骤 4 范围**: 属于 retrieval frontier 核心正确性与安全边界。
- **步骤 5 替代**: 不存在可接受的 fail-open 替代。不能执行 filter 的通道必须跳过并标记
  unavailable/degraded，`None` 不得伪装为 0 分。
- **决策**: `accepted`。
- **design.md 修订**: v2 §3.5。

### F-02 — Workflow、MCP、拒绝与诊断分叉

- **步骤 1 核验**: 成立。`agent/skills/retrieve/skill.py:192-214` 的 MCP 与
  `core/fast_mode.py:119-172,265-293` 不共享同一 workflow。
- **步骤 2 触发**: 不同入口面对 `weak/empty/conflict` 时会产生不一致结果、拒绝或诊断。
- **步骤 3 成本**: 统一状态机有重构成本，但可避免入口相关行为和重复诊断写入。
- **步骤 4 范围**: 直接影响新增检索流程的对外契约。
- **步骤 5 替代**: 共享 workflow 是最小可靠方案；三类状态必须有确定终态，diagnostics 只允许
  一个 owner，MCP 不得复制判断逻辑。
- **决策**: `accepted`。
- **design.md 修订**: v2 §4.1/§4.4。

### F-03 — BGE 原子失败与缓存指纹

- **步骤 1 核验**: 成立。`models/bge_m3_embeddings.py:201-223` 的 encode 是批次原子调用；
  `core/retrieval/cache.py:140-159` 的 query cache key 仅含文本。
- **步骤 2 触发**: 模型异常使整次调用失败；模型、维度、归一化或预处理变化会命中陈旧缓存。
- **步骤 3 成本**: 逐 head 重试和混合向量会显著增加复杂度，且不提供更强一致性。
- **步骤 4 范围**: 限于 embedding adapter 与 cache contract。
- **步骤 5 替代**: 一次前向成功则整批采用；任何原子异常均丢弃该次 BGE 结果，转安全 legacy 并标
  degraded，禁止部分混用。缓存键加入模型标识、版本、维度、归一化和预处理 fingerprint。
- **决策**: `defended-with-alternative`。
- **design.md 修订**: v2 §3.2/§6。

### F-04 — ColPali 资产生命周期

- **步骤 1 核验**: 成立。`documents/pdf_parser.py:89-111` 对文本页不渲染；
  `documents/pdf_parser.py:445-464` 使用 filename stem。
- **步骤 2 触发**: 混合 PDF、同名文件、重传或删除均可能造成缺页、碰撞或孤儿资产。
- **步骤 3 成本**: 补齐资产登记与清理成本低于错误视觉召回及存储泄漏风险。
- **步骤 4 范围**: 仅覆盖 ColPali 所需页面资产，不扩展为通用对象存储平台。
- **步骤 5 替代**: 需完整页面策略、基于 file hash 与页码的命名，以及替换、删除、失败回滚和 GC。
- **决策**: `accepted`。
- **design.md 修订**: v2 §5.4。

### F-05 — RAPTOR generation 与 freshness

- **步骤 1 核验**: 成立。若无 generation 边界，增量构建会暴露新旧层级混合状态；
  `documents/graph_store.py:348-483` 已提供可复用的事务 replace 先例。
- **步骤 2 触发**: 重建中断、源文档更新或并发读取即可触发。
- **步骤 3 成本**: 分代暂存与原子切换成本可控，可消除陈旧摘要和半成品树。
- **步骤 4 范围**: 属于 RAPTOR 发布一致性，不要求同时解决摘要质量。
- **步骤 5 替代**: 无弱化方案可提供同等保证；必须按源 hash 校验 freshness，完整构建后事务
  publish，失败保留上一有效 generation。
- **决策**: `accepted`。
- **design.md 修订**: v2 §5.2。

### F-06 — Benchmark 隔离

- **步骤 1 核验**: 成立。`scripts/run_benchmark.py:250-268` 把语料写入当前 collection。
- **步骤 2 触发**: 任意连续数据集/variant、缓存预热或参数变更都会污染运行数据和测量结果。
- **步骤 3 成本**: 临时 URI/collection/独立进程成本有限，收益是结果可复现与现有数据安全。
- **步骤 4 范围**: 仅要求资源与配置隔离，不要求另建完整部署。
- **步骤 5 替代**: 使用唯一 run id 创建隔离资源，固定输入快照，每个 variant 独立进程并在异常后
  清理；不允许复用工作 collection。
- **决策**: `accepted`。
- **design.md 修订**: v2 §8.1。

## 范围外问题清单

无。六条 finding 均属于本 feature 范围。

## 诚实承认的有限边界

- 本轮不训练或替换 embedding/生成模型，也不承诺 RAPTOR 生成式摘要质量。
- ColPali 首阶段只承诺页面定位；文本生成器不具备纯视觉关系推理能力。
- “frontier runtime 离线”只约束新增可选通道不得隐式下载；既有显式配置的 API embedding provider
  仍保持兼容。
- 确定性 `conflict` 只覆盖结构化版本/状态冲突，不声称识别任意自然语言矛盾。
