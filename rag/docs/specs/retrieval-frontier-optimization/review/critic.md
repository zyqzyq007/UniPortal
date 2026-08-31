# Critic 报告 — retrieval-frontier-optimization

**评审对象**: `docs/specs/retrieval-frontier-optimization/design.md` (v1)
**评审模式**: 完整 critic（热路径不变量 + 数据生命周期 + 可复现性）
**评审日期**: 2026-07-16

## 摘要

- Critical: 2 条
- High: 4 条
- Medium: 0 条
- Low: 0 条
- 结论: 必须修订出 v2，所有 Critical/High 在编码前闭环。

## Findings

### F-01 — Filter capability 未闭合 fail-closed

- **id**: F-01
- **severity**: Critical。复杂过滤在 legacy BM25、graph 和同步 fallback 上均可触发越界结果，符合
  critic 严重性量表 §2 的“目标安全边界仍可复现”。`issue (blocking, must-fix)`。
- **location**: `docs/specs/retrieval-frontier-optimization/design.md` §4.1/§11；
  `core/retrieval/hybrid_retriever.py:377-384,487-500`；
  `core/retrieval/graph_retriever.py:123-137,474-501`；触及安全过滤与 §8 混合检索降级不变量。
- **symptom**: legacy BM25 忽略 filter；graph 解析复杂 filter 失败时 fail-open；同步 dense 降级路径
  丢失 filter。设计仅声明原则，没有 typed capability 或 fail-closed 契约。
- **impact**: 请求可能返回过滤范围外的数据，破坏租户、权限或业务范围隔离；多个降级分支均可稳定
  触发。
- **root_cause**: filter 被作为可选字符串透传，缺少后端能力声明、解析结果类型和统一降级决策。
- **recommendation**: 在 `core/retrieval/filter_scope.py` 定义 typed filter scope/capability；执行前验证
  通道支持度。无法安全表达或解析时必须排除该通道，或切换到明确支持等价过滤的后端；禁止静默
  删除 filter。diagnostics 记录降级原因但不得记录敏感过滤原文。
- **verification**: 单元覆盖 unsupported/parse-error/sync-fallback；进程内 E2E 断言任何分支均不越过
  filter；加入复杂过滤永久回归用例。
- **status**: open

### F-02 — Workflow 缺少 MCP、拒答与 diagnostics 所有权接线

- **id**: F-02
- **severity**: High。位于生成前热路径且 shared-state 键所有权未定义，符合 §2 的热路径与
  §4.1 不变量触发条件。`issue (blocking, must-fix)`。
- **location**: `docs/specs/retrieval-frontier-optimization/design.md` §4.1/§6；
  `agent/skills/retrieve/skill.py:192-214`；`core/fast_mode.py:119-172,265-293`；触及 §4.1
  shared_state 所有权与 §8 MCP 降级。
- **symptom**: 未明确 MCP consumer；`weak/conflict/empty` 没有到最终拒答的确定接线；diagnostics
  键缺少 owner、schema 与 reducer 契约。
- **impact**: 弱证据、冲突证据或空结果可能继续生成确定性答案；并行节点还可能整键覆盖诊断信息。
- **root_cause**: 设计停留在组件级，缺少端到端状态机、消费者清单与命名空间责任表。
- **recommendation**: 在 design v2 补全 producer→consumer→decision 流程；为三类结果定义不可绕过的
  生成/信息缺口语义；为 `retrieval_diagnostics` 分配唯一 producer、schema 与整键覆盖规则，并明确
  MCP 的输入输出契约。
- **verification**: E2E 分别注入 weak/conflict/empty，断言最终行为；并发测试验证 diagnostics 无覆盖
  丢失；MCP 与 direct workflow 结果一致。
- **status**: open

### F-03 — One-pass 原子失败与 query cache 身份不成立

- **id**: F-03
- **severity**: High。编码失败降级承诺不可实现，且模型切换可能复用旧向量，符合 §2 的热路径失效
  与缓存失效路径未覆盖。`issue (blocking, must-fix)`。
- **location**: `docs/specs/retrieval-frontier-optimization/design.md` §3.2/§7；
  `models/bge_m3_embeddings.py:201-223`；`core/retrieval/cache.py:140-159`；触及 §8 BGE-M3 与缓存降级。
- **symptom**: 单次 `model.encode` 是原子调用，设计中的 partial survival 不可实现；缓存键仅含 query
  text，缺 provider/model/revision/config fingerprint。
- **impact**: 编码失败时真实行为与降级承诺不一致；模型切换或升级后可能复用旧向量，造成隐蔽检索
  漂移。
- **root_cause**: 将逻辑输出通道误当作独立故障域，并低估 embedding 身份对缓存正确性的影响。
- **recommendation**: 删除 partial-survival 承诺，定义原子失败后转向可用 legacy leg；缓存键至少纳入
  provider、model/source、revision、维度、归一化和查询指令指纹。
- **verification**: 故障注入证明原子失败走安全降级；切换任一 fingerprint 字段均 cache miss；相同配置
  保持命中。
- **status**: open

### F-04 — ColPali 页面资产生命周期不完整

- **id**: F-04
- **severity**: High。常见含文本层 PDF 可触发缺页资产，同名文件可覆盖，属于持久化边界与必要回归
  测试缺失。`issue (blocking, must-fix)`。
- **location**: `docs/specs/retrieval-frontier-optimization/design.md` §5.4/§10；
  `documents/pdf_parser.py:89-111,415-464`；触及持久化模块路径、安全文件名与删除一致性。
- **symptom**: 含文本层页面不生成 page asset；资产仅覆盖 OCR 页；filename stem 可碰撞；缺少全页
  stable hash、更新、删除和原子发布设计。
- **impact**: 引用页可能无可展示资产，不同文档可能互相覆盖；更新或删除后残留陈旧页面，导致证据
  错配。
- **root_cause**: 资产被视为 OCR 副产物，而非与文档版本绑定的持久化实体。
- **recommendation**: visual-enabled 时统一渲染所有页面；以 file hash + page index 生成稳定唯一键；
  采用 staging→atomic publish，并定义重建、删除、失败回滚和孤儿清理。
- **verification**: 覆盖文本页、OCR 页、同 stem 文档、更新缩页、删除及发布中断；断言引用与资产版本
  一致且无孤儿。
- **status**: open

### F-05 — RAPTOR 缺少可见代次和 freshness 闭环

- **id**: F-05
- **severity**: Critical。查询可读取半成品、旧版或已删除来源的摘要节点，破坏热路径正确性与删除
  一致性，符合 §2 的“引入新 Critical 级失效”。`issue (blocking, must-fix)`。
- **location**: `docs/specs/retrieval-frontier-optimization/design.md` §5.2/§6/§10；对照
  `documents/graph_store.py:348-483` 的事务式 source replace；触及 §8 检索降级与持久化契约。
- **symptom**: 缺 source content hash、`building/ready` generation、事务发布、remove 与 stale detection。
- **impact**: 查询可能读取半成品树、旧树或已删除来源的摘要节点；这些节点可能跨版本污染回答且无法
  可靠追溯。
- **root_cause**: 构建过程没有版本化状态机，读写共享同一可见命名空间。
- **recommendation**: 以 source hash 标识代次；构建写入不可见 generation，仅在完整校验后事务切换
  为 `ready`；查询只读 ready generation；定义替换、删除、失败回滚、陈旧扫描及垃圾回收。
- **verification**: 并发查询/构建、构建中断、源更新、源删除测试；断言从不读取 building generation，
  旧 generation 可回收且删除后不可检索。
- **status**: open

### F-06 — Benchmark 缺少 dataset×variant 实验隔离

- **id**: F-06
- **severity**: High。索引、singleton 与 cache 交叉污染会直接使上线决策不可采信，属于缓存失效和
  必要回归门禁缺失。`issue (blocking, must-fix)`。
- **location**: `docs/specs/retrieval-frontier-optimization/design.md` §8；
  `scripts/run_benchmark.py:71-109,250-335,445-483`；触及 §7 测试确定性与 REQ-RFO-026/028。
- **symptom**: runner 复用当前 collection；无 dataset×variant 隔离；未重置 singleton/cache；缺 MRR、
  nDCG、资源消耗及 forward count。
- **impact**: 样本、索引和缓存可能跨变体污染，结果不可复现且无法证明收益来自算法而非预热或调用
  预算增加。
- **root_cause**: runner 未把数据、索引、进程状态和资源预算纳入实验边界。
- **recommendation**: 每个 dataset×variant 使用独立临时 URI、collection 与 registry path；固定配置
  快照；每个 variant 独立进程或显式 reset singleton/cache；报告 Recall、MRR、nDCG、延迟、内存/显存、
  forward count 与降级率。
- **verification**: 交换变体执行顺序结果应等价；检查 collection 唯一性与 reset 证据；资源及 forward
  指标完整落盘。
- **status**: open
