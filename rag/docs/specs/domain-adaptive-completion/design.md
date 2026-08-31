# 领域自适应收尾 — 设计

## 架构（无变化，本 spec 是收尾）

```
data/profiles/<name>.yaml   ← 领域配置(单一事实来源)
        │ load_domain_profile(name)        # 默认 general(REQ-A-001)
        ▼
core/prompts/domain_profile.py  DomainProfile dataclass + active profile
        │ get_active_profile()
        ▼
所有消费者(guardrails / classifier / chat / skills / judge / fast_mode / ...)
        │
core/prompts/profile_prompts.py  ← 重命名自 aircraft_prompts.py(REQ-A-004)
        │ 向后兼容常量派生(运行时用 get_active_profile() 而非常量)
```

本 spec **不改变架构**，只完成三件事：(1) 拔除残留航空硬编码 → profile 化；
(2) 默认 general + 重命名去领域绑定；(3) 文档/契约对齐定位。

## Stage 1 — 功能性耦合修复（影响行为）

### 1a. retrieve 启发式 profile 化
**现状**：`agent/skills/retrieve/skill.py:283-293` 硬编码 4 个航空正则
（`_ATA_RE`/`_FAULT_CODE_RE`/`_SYMPTOM_RE`/`_DIAG_RE`），`_decide_transform` 据此
决定 HyDE/multi_query/None。**这些正则不经 profile**，是真正的领域逻辑耦合。

**设计**：`DomainProfile` 增 3 个可选字段：
- `query_anchor_patterns: list[str]` — 精确锚点正则（ATA/故障码），命中→跳过 transform。
- `symptom_keywords: list[str]` — 抽象症状词（振动/泄漏…），短查询命中→multi_query。
- `diagnostic_keywords: list[str]` — 诊断动词（如何/为什么/原因…），命中→hyde。

`aviation_phm.yaml` 填入现有航空正则/词表（保持行为零变化）；
`_general_defaults` 用**通用**诊断动词（如何/为什么/原因/分析/怎样/怎么办）+
空锚点 + 空症状词。`_decide_transform` 改为编译 profile 的 pattern list（首次编译缓存）。

**不变量**：aviation profile 下 `_decide_transform` 输出与现状逐字节一致（行为契约）。
general profile 下 ATA/故障码/EICAS 等永不命中（航空正则只活在 aviation_phm.yaml）。

### 1b. fast_mode 兜底文案 profile 化
**现状**：`core/fast_mode.py:131/191/243` 硬编码「请先通过文档管理页面上传排故手册、
维修手册等资料」，与 generate skill 不一致（后者已读 `empty_context_message`）。

**设计**：3 处统一改 `get_active_profile().empty_context_message`。aviation profile
的 `empty_context_message` 正是这段文案（见 aviation_phm.yaml:289），行为零变化；
general profile 下用中性文案。

### 1c. pii operational fallback 语义修正
**现状**：`agent/guardrails/pii.py:108-110` `if not out: return _OPERATIONAL_PATTERNS`
——profile 声明**空列表**与**未声明字段**同等待遇，导致 general profile（显式空）
仍 fallback 到内置航空 tail_number/MSN 正则（虽然默认 `PII_DETECT_OPERATIONAL_IDS=false`
时惰性，但开启即泄漏航空模式）。

**设计**：用模块级 sentinel 区分「显式空」与「未声明」：
- `DomainProfile` 加 `pii_operational_patterns_declared: bool`（`from_dict` 检测 key 是否存在）。
- `_operational_patterns_from_profile`：**显式声明**（哪怕空）→ 不 fallback；
  **未声明** → fallback 内置航空模式（向后兼容旧 profile）。
- general/aviation_phm 均**显式声明** `pii_operational_patterns`（前者空、后者有），
  故二者都不再 fallback。

### 1d. 启动日志去硬编码
`api/main.py:85` `f"PHM Prompt Profile: phm_diagnosis_v1 (sig=...)"` →
`f"Domain Profile: {profile.name} (label={profile.prompt_profile_generate}, sig=...)"`。

## Stage 2 — 默认 general（BREAKING）

`load_domain_profile` 默认 `name` fallback：`(name or os.getenv("DOMAIN_PROFILE") or "general")`。
`agent/context/session.py:21` `prompt_profile` 默认值改 `field(default_factory=...)` 派生。
`.env.example` 增 `DOMAIN_PROFILE=general`（注释引导航空用户设 `aviation_phm`）。
CHANGELOG `[breaking]` 记录迁移路径。

## Stage 3 — 标签后缀可配置

`DomainProfile` 加 `profile_suffix: str = "v1"`。属性改：
```python
prompt_profile_generate = f"{self.profile_label}_{self.profile_suffix}"
```
- `aviation_phm.yaml` 显式 `profile_suffix: "diagnosis_v1"` → 保持 `phm_diagnosis_v1`。
- `general` 用 `general_v1`（去 `_diagnosis`）。

**测试同步**：`test_domain_profile.py:97`（aviation 不变）、`:167`（general→`general_v1`）、
`test_eval_flywheel.py:68`（aviation eval 不变）。

## Stage 4 — 重命名

| 旧 | 新 | 向后兼容 |
|----|----|---------|
| `core/prompts/aircraft_prompts.py` | `core/prompts/profile_prompts.py` | 不保留旧 shim（内部全更新；CHANGELOG 注 import 路径变更） |
| `PHM_IDENTITY_RESPONSE` 常量 | `IDENTITY_RESPONSE` | 无（内部） |
| `PHMDiagnosis` 类（api schema + 前端 interface） | `StructuredAnswer` | `PHMDiagnosis = StructuredAnswer` 别名保留（API 契约，可能有外部引用） |
| `_extract_phm_diagnosis` | `_extract_structured_answer` | 无（内部） |
| `_looks_like_phm_query` | `_looks_like_domain_query` | 无（内部） |

9 个 importer 路径同步：`core/fast_mode.py`、`core/intent/classifier.py`、
`api/main.py`、`api/routers/chat.py`、`agent/mcp/retriever_tools.py`、
`agent/skills/{agent,generate,grade,rewrite}/prompts.py`。

## Stage 5 — 前端去硬编码

`web/src/views/ChatView.vue`：欢迎语、快捷按钮、模式卡文案、`getProfileLabel` 映射
全部领域中性化（去掉「航空」「PHM」「发动机/液压/航电」等硬编码，改通用示例）。
`web/src/stores/chat.ts`：`PHMDiagnosis` → `StructuredAnswer`（+ type alias）。
保留 `data-testid` 不变（Playwright 不依赖按钮文案）。

## Stage 6 — 文档全量更新

逐文件去「系统=航空 PHM 产品」硬断言，保留历史/示例航空引用。详见 tasks.md。
关键：README/AGENTS/technical_report/API 的「是什么」陈述改领域无关；示例 payload
保留 1 个航空示例并标注。

## 数据流/状态契约
- `shared_state` 键：**无变化**。
- REST API：`metadata.diagnosis` 字段名保留（避免破坏），仅类型注释改 StructuredAnswer；
  响应体形状零变化（`PHMDiagnosis` 别名同形）。
- env：新增 `DOMAIN_PROFILE` 默认值语义变更（BREAKING）。

## 降级矩阵
**无变化**。本 spec 不动熔断器/降级路径；profile 化的启发式仅在「有文档」路径生效，
空知识库走 `empty_context_message`（已 profile 化）。

## 不变量影响
- 加载失败仍回退 general（永不抛）——不变。
- active profile 进程级缓存——不变。
- aviation_phm 默认行为（在 `DOMAIN_PROFILE=aviation_phm` 下）逐字节不变——不变。

## 安全影响
- pii fallback 修正（1c）：general profile 下不再静默装航空正则——正向（减少误判）。
- input_guardrail topic allow-list 已 profile 化——不变。
- judge 间接注入防护——不变。

## 回滚
- 每 stage 独立 commit，可逐 stage revert。
- Stage 1/2/3 改动集中在 `domain_profile.py` + 2 yaml + 几个消费者，revert 即恢复。

## 测试矩阵
- 单元：`tests/unit/test_domain_profile.py`（扩字段、suffix、anchor/symptom 读取）、
  `tests/unit/test_pii.py`（general 无 fallback）、新增 retrieve 启发式 general 行为测、
  fast_mode 兜底文案测。
- 进程内 E2E：`tests/e2e/test_e2e_domain_switch.py`（默认 profile 断言更新）、
  `tests/e2e/test_e2e_chat.py`（StructuredAnswer 抽取）。
- Playwright：`tests/e2e_ui/chat.spec.ts`（文案断言同步）。
- import smoke：`python -c "import api.main"`。

## 风险（RISK）
- 默认 profile 切换 BREAKING：CHANGELOG + `.env.example` 引导，不静默。
- 重命名级联：9 importer + chat.py 多处 + 前端 + 3 测试，import smoke + 全量测试守护。
- `_decide_transform` 行为契约：aviation 逐字节不变需 golden 测守护。
