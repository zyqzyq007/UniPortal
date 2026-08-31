# 通用 RAG Benchmark — 需求

## 范围
用**领域无关的公开 QA 基准**测 RAG 通用检索+生成能力(非航空专项),验证阶段 D 的领域自适应 Agent 在通用语料上的效果。规则评分优先(judge 可选),CI 可跑。

## 本质需求(ESSENTIAL)
- benchmark 数据集与领域无关(英文 MS MARCO/HotpotQA/NQ + 中文 DuReader/CMRC2018),测检索召回/精准 + 答案正确性。
- context_precision/recall 必须可**离线确定性计算**(基于 expected_context_ids),不依赖 LLM,让这两维不再 n/a。
- 数据集准备脚本化、可离线回放(气隙友好)。

## 需求项(EARS)

- **REQ-C-001**: MUST 提供 `scripts/prepare_benchmark.py`,从公开源拉取并转换成项目 `EvalCase` 格式(含 query/reference_answer/expected_context_ids/corpus),落盘 `data/benchmark/`。
- **REQ-C-002**: MUST 提供至少一个内置(无需联网)的小型 benchmark 子集作为默认/CI 用例(避免 CI 依赖网络)。
- **REQ-C-003**: EvalScorer MUST 新增确定性 context_precision/recall(基于 expected_context_ids 与实际召回 id 的集合运算),不依赖 judge。
- **REQ-C-004**: MUST 提供 `scripts/run_eval.py --dataset data/benchmark/<name>.yaml --domain-profile <name>` 支持,切换 profile 跑通用 benchmark。
- **REQ-C-005**: MUST 有单测覆盖:数据集加载/schema、context 指标计算正确性(确定性 golden)。

## 不在范围
- 在线 judge 全维度(保留可选,但默认规则)。
- 大规模语料下载(子集即可,~20-50 条/benchmark)。
