# 主链路领域泛化（Domain Generalization）— 需求

## 范围

把当前「默认航空 PHM」的领域自适应 RAG 系统，泛化为**默认领域无关**的主链路：主代码、品牌、文档、测试默认路径不再出现任何航空/PHM 字样；`aviation_phm.yaml` 降级为**可选示例 profile**，仅用于证明系统能嵌入航空航天领域。`DOMAIN_PROFILE` + `DomainProfile` + `data/profiles/` 领域自适应机制完整保留。

## 范围切分

- **在范围内（IN-SCOPE）**：主代码运行时路径去航空化、PII 航空 regex fallback 移除、StructuredAnswer API 字段泛化、eval/golden/测试夹具通用化、品牌/脚本/文档通用化。
- **不在范围内（OUT-OF-SCOPE，刻意保留）**：
  - `data/profiles/aviation_phm.yaml` + `md/phm_test_knowledge_base.md`（+ PDF）：作为「航空航天嵌入示例」保留，文件内 PHM 字样是预期的。
  - `CHANGELOG.md` 历史条目 + `docs/specs/*/review/*.md` 历史评审记录：保留不可篡改的变更历史。
  - GitHub org `PHMgogooo`：外部依赖，需在 GitHub 侧改名，代码层面仅加注释标注。

## 本质需求（ESSENTIAL）

- 系统默认（`DOMAIN_PROFILE` 未设）开箱即为领域无关的通用 RAG，主代码路径不含任何航空领域假设。
- 领域自适应机制（profile 加载/切换/新增）保持完整可用，`aviation_phm` 作为可选示例可被正确加载。
- 消除主代码中所有「潜在继承航空行为」的耦合点（PII regex fallback、航空偏向字段名、硬编码维修手册提示）。
- 公共 API 契约字段泛化为通用语义（breaking change，须迁移指南）。

## 表面需求 vs 本质需求

| # | 表面（SURFACE） | 本质（ESSENTIAL） |
|---|-----------------|-------------------|
| 1 | 「删除所有 phm 字样」 | 主链路去领域耦合；航空内容收敛到「可选示例 profile」单一事实来源 |
| 2 | 「重命名字段」 | API 契约语义中立，不暗示任何具体领域（诊断/医疗） |
| 3 | 「换掉测试数据」 | 回归契约验证「通用 RAG 能力」而非航空行为 |

## 需求项（EARS）

### PII fallback 去耦合
- **REQ-DG-001**（MUST）：`agent/guardrails/pii.py` 的 `_operational_patterns_from_profile()` **MUST** 仅从 active profile 的 `pii_operational_patterns` 读取；profile 未声明该键时 **MUST** 返回空列表（不再 fallback 到任何内置领域 regex）。
- **REQ-DG-002**（MUST NOT）：主代码（`agent/` `core/` `api/` `web/src/`）**MUST NOT** 包含硬编码的领域标识符正则（机尾号/MSN 等）；此类模式 **MUST** 仅存在于 profile YAML。
- **REQ-DG-003**（MUST）：`core/prompts/domain_profile.py` **MUST** 移除 `pii_operational_patterns_declared` 字段及其所有引用（该字段仅为兼容航空 fallback 而存在）。

### StructuredAnswer API 泛化（breaking）
- **REQ-DG-004**（MUST）：`api/routers/chat.py` 的 `StructuredAnswer` **MUST** 使用领域无关字段名（`summary`/`details`/`steps`/`notes`/`sources`/`gaps`），**MUST** 删除 `PHMDiagnosis` 向后兼容别名。
- **REQ-DG-005**（MUST）：API 响应 metadata 键 **MUST** 从 `diagnosis` 改为 `structured_answer`；前端 store 与视图 **MUST** 同步改名。
- **REQ-DG-006**（MUST）：`_extract_structured_answer` 的位置映射（profile.section_template → 字段）**MUST** 保持，仅字段名改变。

### 硬编码用户面字符串
- **REQ-DG-007**（MUST）：`agent/skills/agent/skill.py` 的 nudge 文案、`agent/guardrails/output_guardrails.py` 的 caveat、`api/routers/chat.py` 的 log/注释 **MUST** 不含「维修手册/手册/PHM」等领域字样，改为领域无关措辞。

### Eval/数据/测试通用化
- **REQ-DG-008**（MUST）：`data/eval/golden.yaml` 与 `agent/eval/cases.py` **MUST** 改为领域无关的通用知识问答案例（`expected_sections:[]`，不假设任何垂直领域）。
- **REQ-DG-009**（MUST）：`tests/` 下所有夹具（罐装文档、示例查询、断言）**MUST** 改为领域无关内容；默认 profile（general）下的测试路径 **MUST NOT** 出现航空字样。
- **REQ-DG-010**（MUST）：`web/playwright.config.ts` 的 webServer **MUST** 不设 `DOMAIN_PROFILE=aviation_phm`，使用默认 general profile。
- **REQ-DG-011**（SHOULD）：`tests/unit/test_domain_profile.py` 与 `tests/e2e/test_e2e_domain_switch.py` **SHOULD** 保留一条轻量断言验证「加载 aviation_phm 示例 profile 成功」（证明系统仍可嵌入航空领域），但默认断言路径不含航空字样。

### 品牌/文档
- **REQ-DG-012**（MUST）：`README.md`、`AGENTS.md`、`deploy.sh`、`run.sh`、`stop.sh`、`.env.example`、`docs/API.md`、`docs/technical_report.md` 的主描述 **MUST** 为领域无关通用平台；`aviation_phm` 仅以「可选示例 profile」身份提及。

### 向后兼容与机制保留
- **REQ-DG-013**（MUST）：`DomainProfile` + `load_domain_profile(name)` + `get_active_profile()` + `data/profiles/` 加载机制 **MUST** 完整保留，可正常加载 `general` 与 `aviation_phm` 两个 profile。
- **REQ-DG-014**（MUST NOT）：本次变更 **MUST NOT** 改动 LangGraph 拓扑、5 个 skills、intent 分类枚举、retrieval 栈的领域无关行为（这些本已领域无关）。

## Breaking changes

- API 响应 metadata 键 `diagnosis` → `structured_answer`（前端/API 消费方需改键名）。
- `StructuredAnswer` 字段名全量重命名（`conclusion`→`summary` 等）。
- 删除 `PHMDiagnosis` 类型别名（前后端）。
- 删除 `DomainProfile.pii_operational_patterns_declared` 字段（profile YAML 不受影响，YAML 层无该键）。
- 以上均在 `CHANGELOG.md [Unreleased]` 标 `[breaking]` 并附迁移指南。

## 验收门禁

- `python -m pytest tests/unit/ tests/e2e/ -q` 全绿。
- `scripts/run_eval.py --no-judge` 在 general profile 下跑通。
- grep 验收：`agent/ api/ core/ web/src/ tests/ utils/ models/ documents/` 主路径命中 `PHM|航空|航天|飞机|维修手册` 仅限于：① 对 `aviation_phm.yaml` 的引用；② 「加载航空示例 profile」的轻量断言。
