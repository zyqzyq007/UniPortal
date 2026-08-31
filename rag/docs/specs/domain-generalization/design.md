# 主链路领域泛化 — 设计

> **版本**: v1.1（2026-06-27）— 闭合 critic F-C1/C2/C3/C4 + defender F-01/F-03/F-06。
> v1 → v1.1 变更：§3.1 PII 改动重框架为 breaking + 承重假设标注；§3.2 UI 标签改为从 profile section_template 派生（闭合 F-C1）；§3.4 eval baseline 步骤；§3.5 测试字段属性断言补全（F-C2/F-03）；§4 测试矩阵补字段名断言行。

## 1. 背景

当前系统运行时核心已通过 `DOMAIN_PROFILE` + `DomainProfile` 实现领域自适应，但默认主链路仍残留航空 PHM 耦合，分布在：PII 航空 regex fallback、StructuredAnswer 航空偏向字段名、硬编码「维修手册」用户面字符串、eval/golden/测试夹具的航空内容、品牌文档的航空定位。本次把航空收敛为「可选示例 profile」，主链路彻底领域无关。

## 2. 架构（不变 + 收敛）

```
保持不变：
  data/profiles/<name>.yaml  ──load──►  DomainProfile  ──get_active_profile──►  所有消费者
  （general 默认 + aviation_phm 示例）

收敛点（本次）：
  主代码 ──×──► 硬编码航空 regex/字段/文案   （删除/泛化）
  主代码 ──► 仅通过 profile 读领域配置（已成立的模式，补齐遗漏）
```

领域自适应机制（`core/prompts/domain_profile.py`、`core/prompts/profile_prompts.py`、`data/profiles/`）**保持不变**，仅删除为兼容航空而存在的 `pii_operational_patterns_declared`。

## 3. 去耦合点详述

### 3.1 PII 航空 regex fallback 移除（REQ-DG-001/002/003）

**现状**（`agent/guardrails/pii.py:81-117`）：
- 模块级 `_OPERATIONAL_PATTERNS` 硬编码机尾号（`B-/N-/G-/CC-`）、MSN 正则。
- `_operational_patterns_from_profile()` 当 profile 未声明 `pii_operational_patterns` 键时，fallback 返回 `_OPERATIONAL_PATTERNS`（航空行为）。
- `DomainProfile.pii_operational_patterns_declared`（`domain_profile.py:167`）仅为区分「显式空」与「键缺失」以控制 fallback。

**改法**：
- 删除 `_OPERATIONAL_PATTERNS` 常量（`pii.py:81-86`）。
- `_operational_patterns_from_profile()`（`pii.py:89-117`）**整体重写**：仅从 `profile.pii_operational_patterns` 读取；未声明或为空 → 返回 `[]`。**整体移除** `declared` 变量与 line 115-116 fallback 分支（避免残留 `_OPERATIONAL_PATTERNS` 引用→NameError，该行在 try 块外不被 `except` 兜底）。
- 删除 `DomainProfile.pii_operational_patterns_declared` 字段 + `from_dict` 中 `"pii_operational_patterns" in data` 逻辑。
- `general.yaml` 已显式 `pii_operational_patterns: []`，行为不变。
- `aviation_phm.yaml` 已显式声明机尾号/MSN 模式，行为不变。
- 新增 profile 忘填该键 → 不再意外继承航空 regex（**这正是修复目标**）。

**Breaking 性质（critic F-C4 / defender F-01 共识）**：此改动对「未声明 `pii_operational_patterns` 键的第三方 profile + `PII_DETECT_OPERATIONAL_IDS=on`」配置组合是**真实行为回归**——旧：隐式继承航空 tail_number/MSN 正则 redact；新：返回 `[]` 不 redact。REQ-DG-001/002/003 须标 `[breaking]`，CHANGELOG 给迁移项：第三方 profile 需显式声明该键以恢复 redact（无需改代码）。仓库内 general/aviation_phm 两个 profile 行为均不变。

**承重假设（critic F-C4）**：「默认行为不变」结论**依赖 `PII_DETECT_OPERATIONAL_IDS` 默认 off**（`pii.py:123`）。此假设须在 CHANGELOG 注明，禁止在未同步评审下把该默认值翻 on。

**降级/安全影响**：PII guardrail 是 §9 安全基线（信息泄露）相关，本次**收紧**而非放宽——人类 PII `PII_PATTERNS`（id_card/phone/bank_card/email/ip/passport，`pii.py:48-73`）与 `_OPERATIONAL_PATTERNS` 完全分离，删除后者不触及前者；默认不 redact 任何 operational id（原行为也是如此）。航空示例 profile 仍可 redact（显式声明）。STRIDE 信息泄露维度正向，无倒退。

### 3.2 StructuredAnswer API 字段泛化（REQ-DG-004/005/006，breaking）

**现状**（`api/routers/chat.py:92-110`）：`StructuredAnswer` 字段 `conclusion/possible_causes/troubleshooting_steps/safety_risks/evidence_sources/info_gaps`，偏向诊断/医疗语义；`PHMDiagnosis = StructuredAnswer` 别名；metadata 键 `diagnosis`。

**改法**（字段重命名，位置映射不变）：
| 旧字段 | 新字段 | 位置语义（不变） |
|--------|--------|------------------|
| conclusion | summary | section_template[0] |
| possible_causes | details | section_template[1] |
| troubleshooting_steps | steps | section_template[2] |
| safety_risks | notes | section_template[3] |
| evidence_sources | sources | section_template[4] |
| info_gaps | gaps | section_template[5] |

- 删除 `PHMDiagnosis = StructuredAnswer`（`chat.py:109-110`）。
- metadata 键 `diagnosis` → `structured_answer`（`chat.py` 13 处：372/392/512/560/666/676/857/893/908/968/978/1077/1091；其中 978 是 stream general_chat 路径内联 dict，**不走 `_build_metadata`**，须单独改）。
- `web/src/stores/chat.ts`：`StructuredAnswer` 接口字段同步；`PHMDiagnosis` 别名删除；`diagnosis` → `structured_answer`（13/126/293）。
- `web/src/views/ChatView.vue`（critic F-C1 / defender F-03 细化）：
  - 模板字段访问 `msg.diagnosis?.X` → `msg.structured_answer?.Y`（129-131, 416-425，共 6 字段）。
  - computed `hasDiagnosis` → `hasStructuredAnswer`（416-428）。
  - CSS class `.diagnosis-card` → `.structured-answer-card`（1024-1041）。
  - **UI 标签策略（闭合 F-C1，关键）**：**不**硬编码通用标签（如「补充说明」），而是从 active profile 的 `section_template` 派生展示标签——后端在响应 metadata 旁附 `section_labels: list[str]`（= `profile.section_template`），前端按字段 idx 渲染对应标签。这样：aviation profile 仍显示「风险与安全提示」等安全语义标签（不稀释安全信号），general profile（section_template 空 → structured_answer 为 null）不渲染卡片，主链路领域无关（标签来源=profile）。字段名（summary/details/steps/notes/sources/gaps）是纯数据契约槽位，不承载领域语义（defender F-02）。

**位置映射不变性**：`_extract_structured_answer` 仍按 `profile.section_template` 顺序映射到字段 index，只是字段名变了。general profile（section_template 空）→ 返回 None（自由回答），行为不变。null 守卫：`chat.py:281-282` 提取失败返回 None；`ChatView.vue` `hasStructuredAnswer` 在 null 时返回 false，`v-if` 不渲染卡片（critic praise 确认成立）。

**不变量影响**：不触及 shared_state 键；不触及 §8 降级矩阵热路径组件（StructuredAnswer 是响应序列化，非热路径）。

### 3.3 硬编码用户面字符串（REQ-DG-007）

| 文件 | 行 | 旧 | 新 |
|------|----|----|----|
| `agent/skills/agent/skill.py` | 142, 241 | `正在为您查询维修手册中的相关内容` | `正在为您检索知识库中的相关内容` |
| `agent/guardrails/output_guardrails.py` | 152-153 | `未经手册直接验证` | `未经知识库直接验证` |
| `api/routers/chat.py` | 596, 601 | `PHM-like query` / `PHM heuristic` | `domain-like query` / `domain heuristic` |

### 3.4 Eval/数据通用化（REQ-DG-008）

`data/eval/golden.yaml` 重写为 ~15 个通用知识问答案例（事实问答/步骤说明/对比/边界/闲聊），`expected_sections: []`，配套通用样例 KB（`md/` 下新增通用文档）。`agent/eval/cases.py` 的 `get_default_eval_cases()` 同步重写为通用兜底。`data/eval/replay_samples.jsonl` 重写。`data/eval/runs/*.json` 删除（gitignored）。

**Baseline 重建步骤（critic F-C3 / defender F-06）**：删 runs 后 `load_history()` 为空 → `--fail-on-regression` 走 `baseline=None` 分支（`run_eval.py:119-137`）→ 打印 "No baseline available — skipping regression gate" → return 0。即**首跑门禁被跳过（ungated）**，不生成基线也不报错。安全重建：(1) 删 `data/eval/runs/*` + `history.jsonl`；(2) `scripts/run_eval.py --no-judge --tag baseline`（ungated 通过，生成首条 history）；(3) 后续 PR 的 `--fail-on-regression` 即以该 run 为基线 compare。golden.yaml 重写改变了案例集，跨集比较本就无意义，ungated 首跑是合理的；但 design v1 措辞「生成新基线」误导，v1.1 改述为「ungated 跳过」。

### 3.5 测试夹具通用化（REQ-DG-009/010/011）

- `tests/conftest.py`、`tests/e2e_ui/_fakes.py`、`tests/e2e_ui/fixtures/sample.md`、`tests/e2e_ui/chat.spec.ts`：罐装文档/查询/断言改通用。**chat.spec.ts 联动（defender F-03）**：canned answer 的 `【诊断结论】` 文本与断言正则 `/诊断|振动|不平衡|频谱/` 须同步去航空化，否则 Playwright 断言失配。
- `tests/e2e/test_e2e_*.py`、`tests/unit/test_*.py`（~7 文件）：航空示例改通用。
- `tests/unit/test_domain_profile.py`（critic F-C2）：`TestAviationProfile` → 通用配置测试；保留「aviation_phm 示例可加载」轻量断言（REQ-DG-011）。**显式点名**：`test_extract_diagnosis_aviation`（208-217）的 `diag.conclusion` 字段属性访问须改 `diag.summary`（保留 aviation 抽取断言，仅改字段名），否则字段重命名后 AttributeError。
- `web/playwright.config.ts`：删 `DOMAIN_PROFILE=aviation_phm`。
- `tests/integration/test_system.py`、`agent/harness/orchestrator.py` doctest、`agent/mcp/retriever_tools.py` CLI 默认：改通用。

## 4. 测试矩阵

| 层 | 用例 | 文件 |
|----|------|------|
| 单元 | PII 未声明 profile → 空模式（不继承航空）；人类 PII 仍检出 | `tests/unit/test_pii.py` |
| 单元 | StructuredAnswer 新字段名 + metadata 新键；`_extract_structured_answer` 返回对象字段名 == 新名 | `tests/unit/test_*` |
| 单元 | domain_profile 加载 general/aviation_phm + 字段完整性 | `tests/unit/test_domain_profile.py` |
| 进程内 E2E | general profile 路由通用查询、不强制结构 | `tests/e2e/test_e2e_domain_switch.py` |
| 进程内 E2E | chat 响应含 structured_answer 新键 | `tests/e2e/test_e2e_chat.py` |
| Eval flywheel | general profile 下 golden.yaml 通用案例跑通 | `scripts/run_eval.py --no-judge` |
| 前端 | web/src 编译通过（新字段名） | `npm run build` |
| Playwright | chat.spec.ts 通用查询断言（默认 general） | `npx playwright test` |

**红绿时序**：PII fallback 用例先写红（断言空），再删 `_OPERATIONAL_PATTERNS`（绿）；StructuredAnswer 用例先写红（断言新字段），再改名（绿）。

## 5. 不变量影响

- **shared_state 键**：无变化。
- **§8 降级矩阵**：无变化（不触及 11 个热路径组件的行为）。
- **§9 安全基线**：PII 收紧（不再有航空 fallback），无倒退；其余域无影响。
- **承重假设（critic F-C4）**：PII「默认行为不变」结论依赖 `PII_DETECT_OPERATIONAL_IDS` 默认 off（`pii.py:123`）。此假设须在 CHANGELOG 注明，禁止在未同步评审下把该默认值翻 on。
- **熔断器**：无变化。
- **prompt 单一来源**：无变化（profile 仍是 SoT）。

## 6. 安全影响（STRIDE 视角）

| STRIDE | 影响 |
|--------|------|
| 信息泄露 | 正向：移除航空 regex fallback，新 profile 不再意外 redact/暴露航空模式假设 |
| 篡改 | 无影响（字段重命名不改语义验证） |
| 其余 | 无影响 |

## 7. 回滚

- 字段重命名/字符串改动可 `git revert` 单 commit。
- PII fallback 删除：若需恢复航空默认 redact，在 profile 显式声明即可（无需改代码）——这正是去耦合的目标态。
- golden.yaml 重写：保留 git 历史，可回滚。

## 8. 风险（RISK）

- **字段重命名波及面广**（后端+前端+API.md 示例）：需逐文件确认无遗漏，用 grep 守护。
- **测试夹具重写可能引入 flaky**：保持罐装内容确定性，不依赖 LLM 输出（conftest mock 单例）。
- **eval golden 改通用后规则评分门禁基线变化**：删除旧 runs，首次跑生成新基线，`--fail-on-regression` 暂用新基线。
- **breaking change 对现有 API 消费方**：CHANGELOG 迁移指南必须清晰（键名+字段名对照表）。
