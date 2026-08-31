# Defender 报告 — domain-generalization

**评审对象**: `docs/specs/domain-generalization/design.md` (v1) — 预评审（critic findings 尚未产出；本报告对设计薄弱点预先独立裁决，供 critic 出 findings 后对照）
**评审日期**: 2026-06-27
**方法论**: `docs/specs/prompts/defender.md` 5 步决策树（事实?→可触发?→成本vs影响?→范围内?→等价替代?）
**核实基础**: 全部基于真实代码 `file:line`，未凭设计描述臆断

## 裁决表

| 发现 ID | 严重性 | 决策 | 理由（file:line 证据 / 不可达证明 / 替代方案） | design.md 修订条目 |
|---------|--------|------|------------------------------------------------|---------------------|
| F-01 | Medium | **accepted** | PII fallback 删除对「未声明键的第三方 profile + opt-in」是真实行为回归，设计 §3.1 仅框定为「修复」，CHANGELOG breaking 清单未覆盖该行为变化 | v2 §3.1 + §8 CHANGELOG |
| F-02 | Low | **defended-with-alternative** | 通用字段名 `details`(可能原因)/`notes`(风险)语义偏弱，但位置映射由 profile.section_label 在 UI 填充，字段名只是契约槽位 | v2 §3.2 附字段语义说明 |
| F-03 | High | **accepted** | `tests/e2e_ui/chat.spec.ts` + `tests/e2e/test_e2e_chat.py` + `web/src/views/ChatView.vue` 的硬编码诊断查询/UI 标签未在字段重命名清单内显式联动，存在前后端契约漂移风险 | v2 §3.2 + §3.5 测试清单补全 |
| F-04 | Low | **rejected (unreachable)** | 「删除 _OPERATIONAL_PATTERNS 破坏现有 PII 测试」场景不可达：test_pii.py:48-68 显式切 aviation_phm profile 验证，不依赖 fallback | — |
| F-05 | Low | **rejected (unreachable)** | 「字段重命名破坏 eval capture / memory extractor / judge」场景不可达：三者均不读 `diagnosis` metadata 键或字段名 | — |
| F-06 | Medium | **defended-with-alternative** | eval golden 重写后 `--fail-on-regression` 行为：删 runs 后无 baseline → run_eval.py:135-137 跳过 gate 返回 0，不阻塞，新基线自动生成 | v2 §3.4 附 baseline 重建步骤 |
| F-07 | Low | **defended-with-alternative** | stream 路径 `chat.py:978` 内联 metadata dict（未走 `_build_metadata`）也含 `diagnosis` 键，需一并改——但设计 §3.2 行号清单(…908/968/978…)已含 978，仅需执行确认 | — |
| F-08 | Low | **acknowledged-in-scope** | `README.md:146` curl 示例引用 `md/phm_test_knowledge_base.md`，属 REQ-DG-012 范围但设计 §3 未细列该行；提醒 Stage 6 一并改 | — |

## 逐条论证（Critical/High 必须展开）

### F-01 — PII fallback 删除对未声明第三方 profile 是真实行为回归
- **步骤 1 核验（事实为真）**：`agent/guardrails/pii.py:114-116` — `if not declared and not out: return list(_OPERATIONAL_PATTERNS)`。即任何未声明 `pii_operational_patterns` 键的 profile，在 `PII_DETECT_OPERATIONAL_IDS=on` 时会 redact `B-1234`/`MSN 12345`。删除后 `_operational_patterns_from_profile()` 仅读 profile，未声明→`[]`（设计 §3.1 改法）。**回归真实存在**。
- **步骤 2 触发**：可触发。场景 = 第三方自建 `data/profiles/<name>.yaml` 未写 `pii_operational_patterns` 键 + 部署设 `PII_DETECT_OPERATIONAL_IDS=on` + 文本含 `B-1234` → 原本 redact 为 `[已脱敏:tail_number]`，现在原样透出。
- **步骤 3 成本 vs 影响**：影响 Medium（仅 opt-in 场景触发，`PII_DETECT_OPERATIONAL_IDS` 默认 off，见 `pii.py:123`）；修复成本 = CHANGELOG 标注 + 提供等价恢复路径，属低成本。
- **步骤 4 范围**：在范围内。这正是 REQ-DG-001 的目标（消除潜在继承航空行为）。
- **步骤 5 替代**：等价恢复路径已存在——profile 显式声明 `pii_operational_patterns` 即可恢复 redact，无需改代码（设计 §7 回滚已点明）。
- **决策**：**accepted**。理由：设计 §3.1 将此框定为纯粹「修复/收紧」，但客观上它是**既是 fix 又是 breaking**的双重性质。`requirements.md` §Breaking changes 清单（行 58-64）只列了 `pii_operational_patterns_declared` 字段删除，**未覆盖 fallback 行为变化**。诚实裁决：不护短为「纯修复」，要求在 CHANGELOG `[Unreleased]` 同步标 `[breaking]` 并附「第三方 profile 未声明该键 + opt-in 场景需显式声明模式」的迁移指引。
- **design.md 修订**：v2 §3.1 末尾补「注意：此改动对未声明 pii_operational_patterns 键的第三方 profile 在 PII_DETECT_OPERATIONAL_IDS=on 下是行为回归，属 breaking；CHANGELOG 须标注并提供 profile 显式声明恢复路径」。

### F-02 — 通用字段名语义偏弱
- **步骤 1 核验**：`api/routers/chat.py:293-300` `_extract_structured_answer` 按 `section_template` 顺序填字段 index；`aviation_phm.yaml:151-157` section 为 [诊断结论, 可能原因, 排查步骤, 风险与安全提示, 依据来源, 信息缺口]。新映射 `notes`(idx3)=「风险与安全提示」、`details`(idx1)=「可能原因」。语义上 `notes` 弱化了安全关键权重，`details` 把「原因」降格为「细节」。**事实成立**。
- **步骤 2 触发**：仅在 UI/消费方把字段名当语义来源时才有误导。当前 `web/src/views/ChatView.vue:129-131` UI 用硬编码「诊断结论：/风险提示：/信息缺口：」标签，**不**消费字段名作语义。
- **步骤 3 成本 vs 影响**：影响 Low（语义弱化不影响数据正确性，只影响命名可读性）。
- **步骤 4 范围**：在范围内（字段泛化是 REQ-DG-004）。
- **步骤 5 替代**：能。字段名是**位置槽位契约**，语义由 active profile 的 section_label 在 UI 层填充。这是位置映射不变性（设计 §3.2）的既定设计——字段名无需承载领域语义。若 critic 建议更贴切命名（如 `causes`/`risks`），反而重新引入诊断/医疗偏向，违背 REQ-DG-004「领域无关」目标。
- **决策**：**defended-with-alternative**。替代方案 = 保持通用名 + 在 design.md §3.2 附「字段名是位置槽位，语义由 profile.section_template 注入；general profile 的 section_template 为空 → `structured_answer` 为 null → UI 不渲染结构卡片」的明确说明，消除字段名=语义的误解。
- **design.md 修订**：v2 §3.2 字段映射表后补语义说明一段。

### F-03 — 字段重命名与前端 UI 标签 / e2e 测试查询的联动缺口（High）
- **步骤 1 核验**：
  - `web/src/stores/chat.ts:33-43, 126, 293` — StructuredAnswer 接口字段 + `PHMDiagnosis` 别名 + `diagnosis` 键读取（设计 §3.2 已列，正确）。
  - `web/src/views/ChatView.vue:129-131, 416-425, 1024-1041` — 字段访问（`msg.diagnosis?.conclusion` 等 6 字段）+ `hasDiagnosis` computed + CSS class。设计 §3.2 列「字段访问重命名 + CSS class」，**但未明确 `hasDiagnosis` 函数名与「诊断结论：」等 UI 标签的处理**。
  - `tests/e2e_ui/chat.spec.ts:39, 44, 49` — 测试名 "with a diagnosis"、查询 `发动机振动异常如何排查？`、断言 `/诊断|振动|不平衡|频谱/`。设计 §3.5 列了 chat.spec.ts 改通用，**但未点明该测试断言依赖 PHM canned answer 的 `【诊断结论】` 文本**。
  - `tests/e2e/test_e2e_chat.py:51, 75, 182` — 查询含「发动机振动/故障诊断」。
- **步骤 2 触发**：可触发。若字段重命名（conclusion→summary）但 ChatView.vue 的 `hasDiagnosis`/字段访问漏改一处 → 前端编译通过但运行时 `msg.diagnosis.summary` 为 undefined，结构卡片静默不渲染（回归）。若 e2e canned answer 不同步改但前端字段改 → Playwright 斆言失配。
- **步骤 3 成本 vs 影响**：影响 High（前端契约漂移是用户可见的功能回归，且 Playwright 是合并门禁）；修复成本 = 在设计清单补全这些联动点，低成本。
- **步骤 4 范围**：在范围内（REQ-DG-005/009）。
- **步骤 5 替代**：无更优替代——必须逐一改。
- **决策**：**accepted**。设计 §3.2 的「字段访问重命名」过于笼统，未把 `hasDiagnosis` 函数名、UI 硬编码标签「诊断结论：/风险提示：」、e2e 断言正则 `/诊断|.../` 显式纳入。
- **design.md 修订**：v2 §3.2 ChatView.vue 子项细化：(a) `hasDiagnosis` → `hasStructuredAnswer`；(b) 模板 `msg.diagnosis?.X` → `msg.structured_answer?.Y` 全量；(c) UI 标签「诊断结论/风险提示」处理策略（建议：general profile 下 structured_answer 为 null 不渲染卡片，aviation profile 下保留领域标签由 section_template 驱动）；v2 §3.5 chat.spec.ts 子项补「canned answer 与断言正则同步去航空化」。

### F-04 — 删除 _OPERATIONAL_PATTERNS 是否破坏现有 PII 测试
- **步骤 1 核验**：`tests/unit/test_pii.py:48-68` `test_tail_number_detected_when_opted_in` 在 `monkeypatch.setenv("DOMAIN_PROFILE","aviation_phm")` 后验证 redact——**显式走 profile 路径，不依赖 fallback**。
- **步骤 2 触发**：不可达。该测试断言的是「aviation profile 显式声明模式生效」，删除 `_OPERATIONAL_PATTERNS` 常量不影响 `aviation_phm.yaml:335-342` 提供的模式。
- **决策**：**rejected (unreachable)**。反证：`test_pii.py:54-60` 用 `aviation_phm` profile 而非 fallback；`pii.py:109-111` 从 `profile.pii_operational_patterns` 编译模式，与 `_OPERATIONAL_PATTERNS` 常量解耦。

### F-05 — 字段重命名是否破坏 eval capture / memory extractor / judge
- **步骤 1 核验**：
  - `agent/eval/capture.py:67-117` — `maybe_capture_inference` 接收 `metadata` 整体透传到 `InferenceRecord`，**不读 `diagnosis` 键**（grep `agent/eval/` for `diagnosis` 无命中）。
  - `agent/memory/extractor.py:10-20` — `_fact_sections()` 用 `section_template[:2]` **位置索引**，不碰 StructuredAnswer 字段名。
  - `agent/eval/judge.py:287,296,553-558` — `conclusions` 是英文「hard claim」类型词，非字段引用。
- **步骤 2 触发**：不可达。三者均不消费字段名或 `diagnosis` metadata 键。
- **决策**：**rejected (unreachable)**。反证如上。设计 §3.2 声称「不触及 memory extractor」属实。

### F-06 — eval golden 重写后 baseline 重建
- **步骤 1 核验**：`scripts/run_eval.py:127-137` — `--fail-on-regression` 在无 prior run 时 `baseline=None` → 打印 "No baseline available — skipping regression gate" → `return 0`。`.gitignore:31-32` `data/eval/runs/*` + `!runs/.gitkeep`；`git ls-files` 确认 `history.jsonl`/`run_*.json`/`benchmark_*.json` 均未跟踪。
- **步骤 2 触发**：可触发但非失败路径。删 runs 后首次跑不报错、不阻塞合并。
- **步骤 3 成本 vs 影响**：影响 Low（首次跑生成新基线即闭环）；修复成本=文档说明，低成本。
- **步骤 4 范围**：在范围内（REQ-DG-008 + 设计 §3.4）。
- **步骤 5 替代**：能。安全 baseline 重建步骤 = (1) 删 `data/eval/runs/*.json` + `history.jsonl`；(2) `scripts/run_eval.py --no-judge --tag baseline`（无 baseline 不阻塞，生成首条 history）；(3) 后续 CI `--fail-on-regression` 即以该 run 为基线。
- **决策**：**defended-with-alternative**。设计 §8 RISK 提及「首次跑生成新基线」但未给可执行步骤。
- **design.md 修订**：v2 §3.4 附「baseline 重建：删 runs → `run_eval.py --no-judge --tag baseline` → 后续 `--fail-on-regression` 以此为基线」。

### F-07 — stream 路径内联 metadata dict 的字段键
- **步骤 1 核验**：`api/routers/chat.py:978` stream general_chat 路径构造 `done_payload` metadata 时内联 `"diagnosis": diagnosis.model_dump() if diagnosis else None`（**未走 `_build_metadata`**）。
- **步骤 2 触发**：若只改 `_build_metadata`（392）漏改 978 → stream general_chat 路径仍吐 `diagnosis` 键，与非 stream 路径 `structured_answer` 键不一致，前端 stream 分支读不到。
- **步骤 3 成本 vs 影响**：影响 Medium（stream/non-stream 契约分裂）；修复成本=改一行+测试。
- **步骤 4 范围**：在范围内。
- **步骤 5 替代**：设计 §3.2 行号清单（372/392/…/908/968/**978**/1077/1091）**已包含 978**。
- **决策**：**defended-with-alternative**（更接近「设计已覆盖，仅需执行纪律」）。替代 = 用 grep 守护（`grep -rn '"diagnosis"' api/` 在改名后应为空）作为合并门禁。无需改 design.md，但建议执行时把 978 标注为「stream-only 内联 dict，非 _build_metadata」。

### F-08 — README curl 示例引用 phm KB
- **步骤 1 核验**：`README.md:146` `curl -F "file=@md/phm_test_knowledge_base.md"`。
- **步骤 2 触发**：是（默认链路文档暴露航空 KB）。
- **步骤 3 成本 vs 影响**：影响 Low（文档示例）；修复成本=换通用示例路径，低成本。
- **步骤 4 范围**：在范围内（REQ-DG-012 README 改通用），但设计 §3 未逐行列该 curl 行。tasks.md Stage 6 `[REQ-DG-012] README.md` 笼统覆盖。
- **决策**：**acknowledged-in-scope**。不另开 backlog（本属 REQ-DG-012），仅提醒执行时改该 curl 示例（换为通用样例 KB 或保留并标注「航空示例」）。

## 范围外问题清单（转 backlog）

| 发现 ID | 转单 issue ID | 说明 |
|---------|---------------|------|
| — | — | 本设计范围清晰，无可转单的真·范围外问题。F-08 虽细，但归属 REQ-DG-012 内。 |

注：`md/phm_test_knowledge_base.md` 保留是 requirements.md §范围切分明确豁免的「航空嵌入示例」，与「主链路领域无关」自洽——它不在默认 eval/retrieval 路径被硬编码加载（`golden.yaml` query 自包含，默认 KB 由文档管理上传决定，非该文件）。该保留不构成泄漏。

## 诚实承认的有限边界

1. **前端 UI 标签来源策略未决**：当前 `ChatView.vue` 的「诊断结论：/风险提示：」是硬编码，字段重命名后这些标签仍航空化。设计 §3.2 说「UI 文案改通用」但未说明是「general profile 下隐藏卡片」还是「标签改通用词」还是「标签从 profile 驱动」。这是 F-03 的核心未决点，需 design.md v2 明确——本报告倾向「general profile (section_template 空) → structured_answer 为 null → 卡片不渲染」，避免硬编码通用词。
2. **未核实的运行时依赖**：本报告未实际执行 `npm run build` / `pytest` 验证编译；所有结论基于静态代码分析。前端字段联动（F-03）的运行时验证依赖红绿测试。
3. **API.md 改动量估算**：`docs/API.md` 有 13+ 处旧字段引用（grep 命中 122-1274），设计 §3 tasks 列「~30 处」属合理量级但未逐行核实是否还有结构化示例块之外的散落引用。
4. **第三方 profile 兼容性**：F-01 的回归仅影响「用户自建未声明键的 profile + opt-in」，仓库内两个 profile（general/aviation_phm）行为均不变，但 CHANGELOG 须为外部消费方明确此点。
5. **GitHub org `PHMgogooo`**：requirements.md §范围切分标注为外部依赖（需 GitHub 侧改名），代码层仅注释标注——此为已知外部限制，不在本设计可控范围。

## 合并门禁自检

- **Critical**：无 Critical 发现。
- **High**：F-03 = accepted，design.md v2 §3.2 + §3.5 须修订（hasDiagnosis 函数名、UI 标签策略、e2e canned answer/断言联动）。
- **Medium**：F-01（accepted，CHANGELOG 补 breaking）、F-06（defended，附 baseline 步骤）均闭环。
- 其余 Low/rejected 不阻塞，F-04/F-05 有 file:line 反证。

**结论**：设计在 PII 去耦合（F-04/F-05 经反证成立）、位置映射不变性、机制保留（profile 加载完整）上工程依据扎实。主要补强点是 F-03 的前端字段联动清单细化（High，必须修订）和 F-01 的 breaking 标注完整性（Medium，必须补 CHANGELOG）。修订完成后可放行进入实现。
