# Critic 报告 — domain-generalization

**评审对象**: `docs/specs/domain-generalization/design.md` (v1)
**评审模式**: 混合（STRIDE — 触及 §9 PII 基线；FMEA — 触及航空安全结构化回答语义；完整 critic — 触及 §4A 正确性）
**评审日期**: 2026-06-27

## 摘要
- 严重 (Critical): 0 条
- 高 (High): 1 条 (F-C1)
- 中 (Medium): 3 条 (F-C2/C3/C4)
- 低 (Low): 0 条
- 结论: **条件可进入编码**。无 Critical，但 F-C1 (High) 触及航空安全信号语义（FMEA RPN=36），编码前必须在 v1.1 中给出「UI 标签从 profile 读取」的明确决策，或在 design.md 中以「已知风险+缓解」显式标注。其余 Medium 可并行编码补定义。Defender 的 F-04/F-05 裁决经独立核实正确（praise 见末）；F-01 经独立核实属实但应重框架为「按设计破坏」。

## Findings

### F-C1 — idx3「风险与安全提示」→`notes` + UI 标签通用化导致航空安全信号被稀释 [issue (blocking, must-fix)]
- **id**: F-C1
- **severity**: High（§2 边界/语义未闭合；§5 FMEA S=4 安全相关 × O=3 偶发(仅 aviation profile active 时) × D=3 中等 → RPN=36 → High）。注：此变更不改 `_extract_structured_answer` 控制流，故不触 §8 热路径「不可用≠0」，但改的是被生成路径产出的安全语义字段的**展示语义**。
- **location**: `api/routers/chat.py:293-300`（位置映射 idx3→`safety_risks`→将改名`notes`）+ `data/profiles/aviation_phm.yaml:155`（section_template[3]=`风险与安全提示`）+ `web/src/views/ChatView.vue:130`（`<strong>风险提示：</strong>{{ msg.diagnosis?.safety_risks }}`）。触及 §4A 正确性。
- **symptom**: 重命名后 aviation 的 idx3「风险与安全提示」内容落到字段 `notes`；design §3.2 又要求 UI 文案「风险提示：」→通用（如「补充说明：」）。结果：当 `DOMAIN_PROFILE=aviation_phm` 时，一段 ARP4761/IEC 60812 视角下 safety-related 的风险提示，在前端以通用「补充说明」标签呈现，掩盖其安全严重性。复现：aviation profile 下问「发动机振动异常」，回答 idx3 含「存在转子不平衡飞转风险」，UI 显示为「补充说明：存在…」。
- **impact**: 维护决策误导风险（S=4）：机务人员可能低估安全提示。仅影响 aviation（及任何把 idx3 用于安全语义的）profile；general profile 无结构化输出，不受影响。
- **root_cause**: design §3.2 把「字段名通用化」与「UI 标签通用化」捆绑，却未让标签从 profile 的 `section_template`（已有，是 SoT）派生——标签仍硬编码在 ChatView.vue。
- **recommendation**: 不要硬编码新通用标签。改为：`ChatView.vue:128-131` 渲染时，从后端随响应附带的 active profile `section_template` 标签读取展示名，按 idx 与字段位置对应渲染。这样主链路领域无关（标签来源=profile），aviation 仍显示「风险与安全提示」，general 不渲染卡片。字段名 `notes` 可保留（纯数据契约），但**展示标签必须可配置**。
- **verification**: Playwright 用例（§7.2）：`DOMAIN_PROFILE=aviation_phm` 下断言 `.structured-answer-card` 内出现字面「风险」标签；`DOMAIN_PROFILE=general` 下断言卡片不渲染（hasStructuredAnswer=false）。单测：构造 idx3 非空的 StructuredAnswer，断言前端拿到的 section_labels[3] == profile.section_template[3]。
- **status**: open

### F-C2 — 后端测试 `test_domain_profile.py:217` 的 `.conclusion` 字段访问是未枚举的破坏点 [suggestion (blocking)]
- **id**: F-C2
- **severity**: Medium（§2 欠定义/可维护性；D=1 易检测—CI 即报）。与 F-03（前端/TS 侧）互补，本条是**后端 Python 侧**的同类遗漏。
- **location**: `tests/unit/test_domain_profile.py:208-217`（`test_extract_diagnosis_aviation`：`assert "振动" in diag.conclusion`）。触及 §4A、§7.2。
- **symptom**: design §3.2 列了 chat.py ~13 处 diagnosis 键 + 前端，§3.5 笼统说「test_domain_profile.py → 通用配置测试；保留 aviation 示例可加载轻量断言」，但未点名本测试用 `.conclusion` **字段属性**断言。字段改 `summary` 后，`diag.conclusion` → AttributeError，该测试红。
- **impact**: build/CI 失败（D=1，被立刻捕获），故无线上风险；但 design 的「grep 守护波及面」清单不完整，违反 §4A「逐文件确认无遗漏」。
- **root_cause**: design 只枚举了 chat.py 与前端的字段访问点，未枚举测试中对 StructuredAnswer 字段属性的访问点。
- **recommendation**: design §3.5 显式追加：`test_domain_profile.py:217` `diag.conclusion` → `diag.summary`（保留 aviation 抽取断言，仅改字段名）；并在 §4 测试矩阵补一行「单测：`_extract_structured_answer` 返回对象的字段名 == 新名」。
- **verification**: 改名后 `pytest tests/unit/test_domain_profile.py::test_extract_diagnosis_aviation` 绿；且新增断言 `assert not hasattr(diag, "conclusion") and hasattr(diag, "summary")`。
- **status**: open

### F-C3 — eval `--fail-on-regression` 首跑是「跳过门禁」非「生成新基线」 [suggestion (blocking)]
- **id**: F-C3
- **severity**: Medium（§2 欠定义；§4A 边界）。Defender「通过」结论技术上正确但低估了风险语义。
- **location**: `scripts/run_eval.py:119-137`（`--fail-on-regression` 分支：`baseline=None` → `print("No baseline available — skipping regression gate."); return 0`）。触及 §4A 边界、design §4 风险。
- **symptom**: design §4 风险行写「删除旧 runs，首次跑生成新基线，`--fail-on-regression` 暂用新基线」。实际代码：删 runs 后 `load_history()` 为空 → `prior=[]` → `baseline=None` → **直接 return 0 跳过门禁**，并不「生成基线」。故首跑对 new golden.yaml 的任何质量回归**零防护**。
- **impact**: golden.yaml 重写本身改变了案例集，跨集比较本就无意义（跳过是合理的）；但 design 措辞误导，使评审者以为首跑有基线保护。若重写引入规则评分 bug（如 expected_sections=[] 导致 section 分恒满），首跑静默绿，回归不被捕获。
- **root_cause**: design 把「无基线→跳过」误述为「无基线→生成基线」；未要求固化一个 committed baseline artifact。
- **recommendation**: design §3.4/§4 改述为「首跑门禁被跳过（ungated）」；并追加：首跑绿后，将本次 run summary 提交为 committed baseline（或记录 run_id），使后续 PR 的 `--fail-on-regression` 真正生效。
- **verification**: 手工：删 `data/eval/runs/*` → `python scripts/run_eval.py --no-judge --fail-on-regression` → 断言 stdout 含 "skipping regression gate" 且 exit 0（证明 ungated）；二次跑（不删 runs）→ 断言走 compare 分支。
- **status**: open

### F-C4 — PII fallback 删除是「按设计破坏」，需 CHANGELOG + 固化默认值假设 [suggestion (blocking)]（独立确认 F-01，补充框架）
- **id**: F-C4
- **severity**: Medium（§2 接口契约/可维护性；§9 PII 基线但方向正向，非倒退）。独立核实 F-01 属实。
- **location**: `agent/guardrails/pii.py:89-117`（`_operational_patterns_from_profile` 当前在 `not declared and not out` 时 fallback `_OPERATIONAL_PATTERNS`，line 115-116）+ `agent/guardrails/pii.py:123`（`PII_DETECT_OPERATIONAL_IDS` 默认 False）。触及 §9 PII 基线、§4A。
- **symptom**: 当前代码：第三方 profile 未声明 `pii_operational_patterns` 键 + `PII_DETECT_OPERATIONAL_IDS=on` → 隐式继承航空 tail_number/MSN 正则。改后 → 返回 `[]`，该配置组合下不再 redact 机尾号。这是**真实行为变更**。复现：新建 profile 不写该键，设 env=on，输入「B-1234 发动机」，改前命中 tail_number，改后不命中。
- **impact**: 对依赖隐式航空 redaction 的第三方部署是破坏性变更；但方向正是修复目标（新 profile 不应继承航空假设）。安全姿态不降级（人类 PII `PII_PATTERNS` 不受影响，见 STRIDE 表）。
- **root_cause**: 「破坏」是预期的，但 design 未把它标 breaking、未给迁移指引；且整个「默认行为不变」结论**依赖 `PII_DETECT_OPERATIONAL_IDS` 默认 off 这一未文档化的承重假设**——若未来有人把默认翻 on，破坏面才显现。
- **recommendation**: (1) design §3.1 显式标 REQ-DG-001/002/003 为 **breaking**，CHANGELOG 给「旧：未声明键+env on→继承航空正则；新→返回空，需在 profile 显式声明」迁移项。(2) design §5「不变量影响」追加一行：`PII_DETECT_OPERATIONAL_IDS` 默认 off 是本设计「默认行为不变」结论的承重假设，禁止在未同步评审下翻默认值。(3) `pii.py:89-117` 重写时**整体移除** `declared` 变量与 line 115-116 fallback 分支（避免残留 `_OPERATIONAL_PATTERNS` 引用→NameError，该行在 try 块外不被 `except` 兜底）。
- **verification**: 单测（§7.2）：(a) monkeypatch 一个无 `pii_operational_patterns` 键的 profile + `PII_DETECT_OPERATIONAL_IDS=on`，断言 `detect_pii("B-1234 故障")` 返回 `[]`；(b) 同 profile + env off，断言人类 PII（如身份证）仍被检出（证明 PII_PATTERNS 未受影响）；(c) general.yaml（显式 `pii_operational_patterns: []`，已确认 `general.yaml:50`）+ env on，断言 `[]`。
- **status**: open

## FMEA 表（模式 A — 航空安全结构化回答）

| 组件 | 失效模式 | 失效影响 | 失效原因 | 现有控制 | S | O | D | RPN | 建议 |
|------|----------|----------|----------|----------|---|---|---|-----|------|
| idx3 字段→UI 标签映射 | safety_risks(风险提示)内容落到 `notes` 且 UI 标签通用化 | 机务低估安全提示，误导维护决策 | 标签硬编码未从 profile 派生 | 无 | 4 | 3 | 3 | **36→High** | F-C1 |
| `_extract_structured_answer` | 提取异常导致 chat 失败 | 响应 500 | — | 返回 None 降级（line 281-282） | 3 | 1 | 2 | 6 | praise（现状已降级，本次不改控制流） |

共因分析（CCA）：无。F-C1 的语义错位是单点，未同时击穿多个独立缓解。

## STRIDE 表（模式 B — PII 基线变更）

| STRIDE 类 | 对本方案的结论 | 证据 |
|-----------|----------------|------|
| 信息泄露 | **正向，确认无倒退** | `PII_PATTERNS`（id_card/phone/bank_card/email/ip/passport，pii.py:48-73）与 `_OPERATIONAL_PATTERNS`（pii.py:81-86）完全分离；删除后者不触及前者。`PII_DETECT_OPERATIONAL_IDS` 默认 off（pii.py:123）→ 默认 redact 行为不变。第三方 profile 失去航空 redact 是 over-可选，非 under-redact。 |
| 篡改 | 无影响 | 字段重命名不改语义验证；redact 输出格式 `[已脱敏:<kind>]` 不变 |
| 欺骗/否认/拒绝服务/权限提升 | 无影响 | 不触及身份/审计/可用性/Admin 路径 |
| OWASP-LLM 注入 | 无影响 | PII LLM pass（pii.py:200-257）未改，temp/circuit-breaker 不变 |

附加 [thought]（非发现）：`pii.py:72` 护照正则 `\b[EeGgKkPpHh]\d{8}\b` 是 always-on 人类 PII，可能在航空语料上对形如 `G12345678` 的序列号**误报 redact**（over-redaction，信息泄露安全但内容失真）。此为既有行为，本次不改，不构成本设计发现；若航空部署反馈误报，可后续 profile 化。机尾号 `B-1234`/`N123AB`（3-5 位数字）与护照（固定 8 位）边界不重叠，无 under-redact 风险。

## 独立核实记录（praise / 反驳）

[praise] **F-04 裁决正确**：`agent/eval/capture.py` 全文无 `diagnosis` 键引用（grep 0 命中）——capture 不读 diagnosis 键，删除/改名不影响 eval 捕获。Defender 正确。
[praise] **F-05 裁决正确**：`agent/memory/extractor.py:10-20` 读的是 `profile.section_template[:2]`（section **标签字符串**，如「诊断结论」「可能原因」），不读 `diagnosis` 键或字段名；字段重命名不影响 memory 抽取。`agent/eval/judge.py`/`grounding_guardrail.py` 的 "conclusion" 是英文 hard-claim 启发式词，非 StructuredAnswer 字段。Defender 正确。
[praise] **web/src 波及面完整**：grep 确认 `web/src` 仅 `ChatView.vue` + `stores/chat.ts` 引用 diagnosis/字段（无其他组件），design §3.2 列举无遗漏。
[praise] **null 守卫降级路径成立**：`chat.py:281-282` `_extract_structured_answer` 空值返回 None；`ChatView.vue:416-428` `hasDiagnosis` 在 `msg.diagnosis` 为 null 时返回 false，`v-if` 不渲染卡片。general profile（`section_template: []`，`general.yaml:17` 已确认）→ 返回 None → 卡片不渲染，行为不变。
[praise] **chat.py diagnosis 键计数准确**：grep 实测 13 处（372/392/512/560/666/676/857/893/908/968/978/1077/1091），design 自列 13 处（文末「~15」措辞略宽，实际更少，无遗漏）。
