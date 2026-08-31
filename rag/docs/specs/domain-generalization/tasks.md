# 主链路领域泛化 — 任务清单

## Stage 0：流程前置
- [x] [REQ-DG-*] 写 `docs/specs/domain-generalization/{requirements,design,tasks}.md`
- [ ] critic + defender 子 Agent 评审，归档 `review/{critic,defender,tracking}.md`

## Stage 1：PII fallback 去耦合（功能层）
- [ ] [REQ-DG-001] `agent/guardrails/pii.py`：删除模块级 `_OPERATIONAL_PATTERNS`；`_operational_patterns_from_profile()` 改为仅从 profile 读，未声明→返回 `[]`
- [ ] [REQ-DG-002] grep 确认 `agent/ core/` 无硬编码机尾号/MSN 正则
- [ ] [REQ-DG-003] `core/prompts/domain_profile.py`：删除 `pii_operational_patterns_declared` 字段 + `from_dict` 中 `"pii_operational_patterns" in data` 逻辑
- [ ] [REQ-DG-001] `tests/unit/test_pii.py`：改为断言「未声明→空」+ 新增「新 profile 不继承航空 regex」用例（红→绿）

## Stage 2：StructuredAnswer API 彻底清理（breaking）
- [ ] [REQ-DG-004] `api/routers/chat.py`：删 `PHMDiagnosis` 别名（109-110）；字段重命名 conclusion→summary/possible_causes→details/troubleshooting_steps→steps/safety_risks→notes/evidence_sources→sources/info_gaps→gaps
- [ ] [REQ-DG-005] `api/routers/chat.py`：metadata 键 `diagnosis`→`structured_answer`（~15 处）
- [ ] [REQ-DG-006] `api/routers/chat.py`：`_extract_structured_answer` 位置映射保留，仅字段名变
- [ ] [REQ-DG-005] `web/src/stores/chat.ts`：删 `PHMDiagnosis`；接口字段同步；`diagnosis`→`structured_answer`（3 处）
- [ ] [REQ-DG-005] `web/src/views/ChatView.vue`：`msg.diagnosis`→`msg.structured_answer`（~10 处）+ 字段访问 + UI 文案 + CSS class 改名

## Stage 3：硬编码用户面字符串去领域化
- [ ] [REQ-DG-007] `agent/skills/agent/skill.py` 142/241：`维修手册`→`知识库`
- [ ] [REQ-DG-007] `agent/guardrails/output_guardrails.py` 152-153：caveat `手册`→`知识库`
- [ ] [REQ-DG-007] `api/routers/chat.py` 596/601：log/注释 `PHM-like`→`domain-like`

## Stage 1-3 验收
- [ ] `python -m pytest tests/unit/ tests/e2e/ -q` 全绿
- [ ] grep `agent/ api/ core/ web/src/` 无 `维修手册|PHM-like`

## Stage 4：eval 数据集通用化
- [ ] [REQ-DG-008] `data/eval/golden.yaml` 重写为通用知识问答（~15 cases，`expected_sections:[]`）+ 配套通用样例 KB
- [ ] [REQ-DG-008] `agent/eval/cases.py` `get_default_eval_cases()` 重写为通用兜底
- [ ] [REQ-DG-008] `data/eval/replay_samples.jsonl` 重写为通用
- [ ] [REQ-DG-008] 删除 `data/eval/runs/*.json`（gitignored，自动重建）

## Stage 5：测试夹具通用化
- [ ] [REQ-DG-009] `tests/conftest.py`：罐装文档/canned_answer/关键词 allowlist 改通用
- [ ] [REQ-DG-009] `tests/e2e_ui/_fakes.py` + `fixtures/sample.md` + `chat.spec.ts`：罐装/查询/断言改通用
- [ ] [REQ-DG-009] `tests/e2e/test_e2e_chat.py`、`test_e2e_replay.py`：查询改通用
- [ ] [REQ-DG-011] `tests/e2e/test_e2e_domain_switch.py`：默认断言改通用；保留「航空示例可加载」轻量验证
- [ ] [REQ-DG-011] `tests/unit/test_domain_profile.py`：`TestAviationProfile`→通用配置测试 + 保留「aviation_phm 示例可加载」轻量断言
- [ ] [REQ-DG-009] `tests/unit/test_input_guardrail.py`、`test_bm25_chinese_tokenization.py`、`test_context_metrics.py`、`test_eval_flywheel.py`、`test_eval_closure.py`、`test_thinking_refusal.py`、`test_query_transform_wiring.py`：航空示例改通用
- [ ] [REQ-DG-010] `web/playwright.config.ts` 33-38：删 `DOMAIN_PROFILE=aviation_phm`
- [ ] [REQ-DG-009] `tests/integration/test_system.py` 3/350：banner 改通用
- [ ] [REQ-DG-009] `agent/harness/orchestrator.py` 152 doctest + `agent/mcp/retriever_tools.py` 362 CLI 默认 query：改通用

## Stage 4-5 验收
- [ ] `python -m pytest tests/unit/ tests/e2e/ -q` 全绿
- [ ] `scripts/run_eval.py --no-judge` 在 general 下跑通

## Stage 6：品牌/脚本/文档通用化
- [ ] [REQ-DG-012] `README.md`：标题/介绍去「首发航空 PHM」；「航空设 aviation_phm」→「可选示例 aviation_phm」；示例换通用
- [ ] [REQ-DG-012] `AGENTS.md`：架构概述去「首发航空 PHM 故障诊断」；FMEA 举例改「可选示例 aviation_phm」
- [ ] [REQ-DG-012] `deploy.sh`/`run.sh`/`stop.sh`：banner 改通用
- [ ] [REQ-DG-012] `.env.example` 4-7：注释改通用
- [ ] [REQ-DG-012] `docs/API.md`：航空示例整体改通用（~30 处）；删 `PHMDiagnosis` 说明；保留「加载 aviation_phm 示例输出航空结构」一句
- [ ] [REQ-DG-012] `docs/technical_report.md`：航空引用改通用
- [ ] [REQ-DG-012] `docs/specs/prompts/README.md`/`critic.md`：FMEA 举例改「可选示例 aviation_phm」
- [ ] `.github/workflows/sync-to-mirror.yml` 25：`PHMgogooo` 加注释标注「需 GitHub 侧改名」

## Stage 7：提交
- [ ] `CHANGELOG.md [Unreleased]` 汇总（含 `[breaking]` + 迁移指南）
- [ ] 最终 grep 验收：`agent/ api/ core/ web/src/ tests/ utils/ models/ documents/` 命中航空字样仅限 ① aviation_phm.yaml 引用 ② 航空示例加载轻量断言
- [ ] PR 拆分（功能/数据测试/文档）+ 测试矩阵结果 + `<!-- RAG_LLM_PR -->`
