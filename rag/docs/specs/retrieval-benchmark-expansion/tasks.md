# Retrieval Benchmark Expansion — Tasks

> 任务仅在实现及所需测试变绿后勾选；每项回指 requirements。

## Stage 0 — Spec and Review

- [x] **T0.1** [REQ-RBE-001..024] 完成 requirements/design/tasks v1。
- [x] **T0.2** [REQ-RBE-001..024] 独立 critic agent 归档 `review/critic.md`。
- [x] **T0.3** [REQ-RBE-001..024] 独立 defender agent 归档 `review/defender.md`。
- [x] **T0.4** [REQ-RBE-001..024, F-01..F-10] 修订 design v2 并在 `review/tracking.md`
  接受/辩护全部 Critical/High。
- [x] **T0.5** [F-02/F-03/F-04/F-05/F-07/F-08] 完成 defender B-01..B-06 的 design v2.1
  快速复核，编码入口门禁归零。

## Stage 1 — Channel Baselines

- [x] **T1.1** [REQ-RBE-004..007, F-01/F-09] 先写 sync/async/parallel、异常 fallback、planner retry
  不复活 disabled 通道的红测试。
- [x] **T1.2** [REQ-RBE-004..007, F-01/F-04] 实现 ActiveChannelPolicy、完整 cache identity、
  request-local execution diagnostics 和默认兼容开关。
- [x] **T1.3** [REQ-RBE-006/020, F-01/F-09] 固化 BM25-only 零 dense forward、双关闭安全空结果、
  不可用不等于 0、filter 不绕过和 documents route 写入→读取回归。

## Stage 2 — Matrix Runner

- [x] **T2.1** [REQ-RBE-001..003/019/021/022, F-05/F-06] 先写 hostile env、balanced schedule、
  effective config、资源预算和 timeout 红测试。
- [x] **T2.2** [REQ-RBE-001..009, F-02/F-05] 实现 local-only named matrix runner、完整 baseline 配置
  和 graph/store/cache 隔离。
- [x] **T2.3** [REQ-RBE-008/009, F-04/F-05/F-08] 实现 reference delta、position drift、双 Pareto、
  stage metrics 和 promotion eligibility。
- [x] **T2.4** [REQ-RBE-002/016/019/023, F-02/F-06/F-07] 固化 zero-network、process-group timeout、
  dotenv 双 canary、parent-dir fsync atomic checkpoint 和失败继续执行。

## Stage 3 — Public Dataset Adapter

- [x] **T3.1** [REQ-RBE-010..015/021/022, F-03/F-07/F-10] 先写 graded qrel、稳定 doc id、
  query/negative 抽样、slug collision、bundle atomic 红测试。
- [x] **T3.2** [REQ-RBE-010..015, F-03/F-07/F-10] 实现通用 `ir_datasets` adapter、generation bundle、
  conversion summary 与 metadata。
- [x] **T3.2a** [REQ-RBE-010/011, F-03] 实现 versioned `ir_measures` public evaluator 和标准 cutoff gate。
- [x] **T3.2b** [REQ-RBE-008/011, F-03/F-08] 分离 `public_quality depth>=100` 与
  `production_performance`，并按 active policy 构建/计量索引。
- [x] **T3.3** [REQ-RBE-011/012/014] 转换 Nano-BEIR SciFact/NFCorpus/FiQA 和 MIRACL-zh sampled。
- [x] **T3.4** [REQ-RBE-013/015, F-02/F-06/F-07] 固化外部不可用、offline cache、重复输出、
  半成品清理和旧 generation 回滚。
- [x] **T3.5** [REQ-RBE-017/018] 记录 private golden 接入和 visual promotion 边界。

## Stage 4 — Experiments and Closure

- [x] **T4.1** [REQ-RBE-008/020, F-05/F-08] 在已有四数据集运行 8-variant balanced matrix；
  完成 256-run 主矩阵，并在修正未判定 MS MARCO 标签后重跑其 64-run slice。
- [x] **T4.2** [REQ-RBE-010..014/020] 在 Nano SciFact/NFCorpus/FiQA 与 MIRACL-zh 运行
  3-baseline balanced public-quality 子矩阵，`36/36` 完成。
- [x] **T4.3** [REQ-RBE-018/020] 复跑 frontier specialized，确认
  `synthetic_encoder=true`、`promotion_eligible=false`。
- [x] **T4.4** [REQ-RBE-020] 运行定向红绿、完整 unit + process-internal E2E、Ruff/import/diff audit；
  最终为 `975 passed, 4 deselected`、`92 passed, 2 skipped`、branch coverage `72%`。
- [x] **T4.5** [REQ-RBE-008/009/020] 在 `benchmark-results.md` 归档质量、延迟、资源、
  Pareto、证据等级、默认与回滚决策。
- [x] **T4.6** [REQ-RBE-001..024] 更新 README/CHANGELOG、HTTP API/MCP、技术报告、测试说明与
  spec 索引，复核 `.env.example` 默认值，并关闭两套 review tracking。
