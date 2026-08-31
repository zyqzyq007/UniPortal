# Tasks — 领域自适应收尾

> 每条 task 用 `[REQ-xxx]` 回指 `requirements.md`。按 stage 分组，逐 stage 独立可合并。
> 红绿时序：先写失败测试（红）→ 实现（绿）。本文件是 PR 可勾选清单。

## Stage 1 — 功能性耦合修复

- [x] [REQ-A-002] `DomainProfile` 加 3 字段：`query_anchor_patterns`/`symptom_keywords`/`diagnostic_keywords`；`_general_defaults` 填通用诊断动词 + 空锚点/症状。
- [x] [REQ-A-002] `aviation_phm.yaml` 填入现有航空 ATA/故障码正则 + 症状词表（保持行为零变化）。
- [x] [REQ-A-002] `agent/skills/retrieve/skill.py` 删 `_ATA_RE/_FAULT_CODE_RE/_SYMPTOM_RE/_DIAG_RE`，`_decide_transform` 改读 profile pattern（首次编译缓存）。
- [x] [REQ-A-002] 红绿：新增单测——aviation profile 下 `_decide_transform` 输出与改前逐字节一致（golden）；general 下 ATA/故障码/症状永不命中。
- [x] [REQ-A-002] `core/fast_mode.py:131/191/243` 3 处空上下文兜底 → `get_active_profile().empty_context_message`。
- [x] [REQ-A-002] 红绿：新增 fast_mode 兜底文案 = profile.empty_context_message 断言。
- [x] [REQ-A-002] `DomainProfile` 加 `pii_operational_patterns_declared: bool`（from_dict 检测 key 存在）；`_general_defaults` + `aviation_phm.yaml` 显式声明。
- [x] [REQ-A-002] `agent/guardrails/pii.py` `_operational_patterns_from_profile`：显式空不 fallback；未声明才 fallback。
- [x] [REQ-A-002] 红绿：`test_pii.py` 增 general profile 下无航空 tail_number/MSN 模式断言。
- [x] [REQ-A-006] `api/main.py:85` 启动日志去硬编码 → 实际 active profile。
- [x] [REQ-A-009] 跑 `python -m pytest tests/unit/ tests/e2e/ -q`（含红绿新测），Stage 1 全绿。

## Stage 2 — 默认 general（BREAKING）

- [x] [REQ-A-001] `domain_profile.py:193` 默认 fallback `aviation_phm` → `general`。
- [x] [REQ-A-001] `agent/context/session.py:21` `prompt_profile` 默认改 `field(default_factory=lambda: get_active_profile().prompt_profile_generate)`。
- [x] [REQ-A-001] `.env.example` 增 `DOMAIN_PROFILE=general` + 注释（设 `aviation_phm` 回退航空）。
- [x] [REQ-A-001] 红绿：`test_e2e_domain_switch.py` 默认 profile 断言更新；新增「无 env=general」测。
- [x] [REQ-A-010] `CHANGELOG.md [Unreleased]` 标 `[breaking]` 写默认切换迁移路径。
- [x] [REQ-A-009] Stage 2 全绿。

## Stage 3 — 标签后缀可配置

- [x] [REQ-A-005] `DomainProfile` 加 `profile_suffix: str = "v1"`；`prompt_profile_*` 属性改 `f"{label}_{suffix}"`。
- [x] [REQ-A-005] `aviation_phm.yaml` 显式 `profile_suffix: "diagnosis_v1"`（保持 `phm_diagnosis_v1`）。
- [x] [REQ-A-005] `general` 用 `general_v1`。
- [x] [REQ-A-005] 红绿：`test_domain_profile.py:97`（aviation 不变）、`:167`（general→`general_v1`）；`test_eval_flywheel.py:68`（aviation 不变）。
- [x] [REQ-A-009] golden/snapshot（标签格式）PR 单列 diff。Stage 3 全绿。

## Stage 4 — 重命名

- [x] [REQ-A-004] `git mv core/prompts/aircraft_prompts.py core/prompts/profile_prompts.py`。
- [x] [REQ-A-004] 更新 9 个 importer 路径（fast_mode/classifier/api.main/chat/retriever_tools/skills×4）。
- [x] [REQ-A-004] 常量 `PHM_IDENTITY_RESPONSE` → `IDENTITY_RESPONSE`（`__all__` + 所有引用）。
- [x] [REQ-A-003] `api/routers/chat.py` `class PHMDiagnosis` → `class StructuredAnswer` + `PHMDiagnosis = StructuredAnswer` 别名。
- [x] [REQ-A-004] `_extract_phm_diagnosis` → `_extract_structured_answer`（更新所有调用点）。
- [x] [REQ-A-004] `_looks_like_phm_query` → `_looks_like_domain_query`（更新所有调用点）。
- [x] [REQ-A-003] `web/src/stores/chat.ts` `interface PHMDiagnosis` → `interface StructuredAnswer` + `export type PHMDiagnosis = StructuredAnswer`。
- [x] [REQ-A-010] `CHANGELOG [Unreleased]` 记 import 路径 + 类型名变更。
- [x] [REQ-A-009] `python -c "import api.main"` smoke + 全量测试。Stage 4 全绿。

## Stage 5 — 前端去硬编码

- [x] [REQ-A-007] `ChatView.vue` 欢迎语/快捷按钮领域中性化（保留 data-testid）。
- [x] [REQ-A-007] `ChatView.vue` 模式卡「检测到 PHM 技术问题」→ 中性文案；「PHM 诊断结构」→「结构化回答」。
- [x] [REQ-A-007] `ChatView.vue` `getProfileLabel` 去 PHM 硬编码映射（通用化或 metadata 派生）。
- [x] [REQ-A-009] `tests/e2e_ui/chat.spec.ts` 文案断言同步（如有）；`cd web && npm run build && npx playwright test`。Stage 5 全绿。

## Stage 6 — 文档全量更新

- [x] [REQ-A-008] `README.md`：标题/概述/能力改全领域；增 `DOMAIN_PROFILE` 说明；embedding 标「默认/可替换」。
- [x] [REQ-A-008] `AGENTS.md`（根）：L89 架构概述、L127 语言策略、L129 prompt 单源路径、L184 FMEA 默认。
- [x] [REQ-A-008] `core/AGENTS.md`：L13/L58 `aircraft_prompts.py`→`profile_prompts.py`。
- [x] [REQ-A-008] `agent/AGENTS.md`：L85 re-export 路径。
- [x] [REQ-A-008] `agent/skills/README.md`：L20-21 re-export 路径。
- [x] [REQ-A-008] `docs/technical_report.md`：标题/概述叙事改全领域；embedding/结构化/eval 标「默认/示例」。
- [x] [REQ-A-003] `docs/API.md`：`PHMDiagnosis`→`StructuredAnswer`（注别名）；示例 payload 领域中性化（留 1 航空示例标注）。
- [x] [REQ-A-008] `docs/specs/prompts/README.md:26` + `critic.md:85`：FMEA 不绑定航空。
- [x] [REQ-A-008] 审视 `docs/specs/*/review/critic.md` 历史评审产物——倾向保留（历史产物不动）。

## 收尾（跨 stage）

- [x] 全量 grep 残留：`aircraft_prompts|PHM_IDENTITY|_extract_phm|_looks_like_phm|phm_diagnosis_v1`(应只在 CHANGELOG/历史 spec/aviation_phm.yaml)。
- [x] [REQ-A-009] 完整测试矩阵：`python -m pytest tests/unit/ tests/e2e/ -q` + Playwright + import smoke。
- [x] [REQ-A-009] adversarial review：critic + defender 子 Agent 评审本 spec（可选，因无新架构）。

## 后续 stage（明确不在本 spec）

- eval/golden 拆 aviation 专项 + 通用默认（`agent/eval/cases.py`、`data/eval/golden.yaml`、`replay_samples.jsonl`）。
- `rag-benchmark-generic` 的 `--domain-profile` flag（REQ-C-004）实现。
- per-request/per-tenant 领域选择（多租户）。
