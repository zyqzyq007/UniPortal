# Requirements — 领域自适应收尾（all-domain completion）

> 本文档为需求陈述（EARS 语法）。设计见 `design.md`，任务清单见 `tasks.md`。
> 每条 task 用 `[REQ-xxx]` 回指本文件需求。

## 1. 背景

项目最初是航空 PHM 故障诊断 RAG，现已重构为**可配置、可自适应的全领域 agent + RAG**。
领域自适应**基础设施已就位**（`DomainProfile` 加载器 + `data/profiles/*.yaml` +
~30 个 profile-gated 消费者 + `tests/e2e/test_e2e_domain_switch.py` 顶石测试），但仍有大量
航空硬编码残留：功能性耦合、领域绑定默认值、领域绑定 API 契约名、文件/标识符名、
未迁移文档、领域绑定前端文案、航空专用 eval 数据集。

本 spec 完成「全领域化」收尾，使项目在外观、契约、默认值、文档上与「全领域」定位一致。

## 2. 本质需求 vs 表面需求

- **本质**：项目应作为**领域无关平台**被认知与使用——默认部署即领域无关，切换/新增
  领域仅靠 `DOMAIN_PROFILE` + YAML，文档与契约名不再误导为单领域产品。
- **表面**：删除/替换所有航空字面量。但历史性、向后兼容性的航空引用（CHANGELOG 记录、
  `aviation_phm.yaml` 作为可选 profile、历史评审产物）应保留。

## 3. 范围（In Scope）

- 功能性领域耦合修复（retrieve 启发式 / fast_mode 兜底 / pii fallback）。
- 默认值切换：`DOMAIN_PROFILE` 默认 → `general`。
- API 契约名重命名：`PHMDiagnosis` → `StructuredAnswer`（保留别名）。
- 代码标识符/文件名全重命名（`aircraft_prompts.py` → `profile_prompts.py` 等）。
- `_diagnosis_v1` 标签后缀可配置。
- 文档全量更新（README / 全部 AGENTS.md / technical_report / API.md / specs/prompts）。
- 前端文案领域无关化（ChatView + chat store）。
- 启动日志去硬编码。

## 4. 不在范围（Out of Scope，明确后续 stage）

- eval/golden 数据集拆分（aviation 专项 + 通用默认）——后续 stage。
- `rag-benchmark-generic` 的 `--domain-profile` flag（REQ-C-004）实现——后续 stage。
- per-request / per-tenant 领域选择（多租户）——不在本 spec。

## 5. 需求（EARS）

### REQ-A-001 默认 profile 切换 [BREAKING]
**WHEN** 进程未设 `DOMAIN_PROFILE` env，**THE SYSTEM SHALL** 使用 `general` profile。
迁移：现有航空部署须在 `.env` 显式设 `DOMAIN_PROFILE=aviation_phm`。`load_domain_profile`
默认参数改为 `general`。

### REQ-A-002 功能性领域耦合零硬编码
**WHEN** 任意领域 profile 被加载，**THE SYSTEM SHALL NOT** 在源码中出现影响行为的
航空字面量。具体：retrieve 启发式词表/正则、fast_mode 空上下文文案、pii operational
fallback 均须由 profile 派生或显式归入 aviation profile。

### REQ-A-003 API 契约领域无关 [BREAKING-contract]
**THE SYSTEM SHALL** 以 `StructuredAnswer` 作为结构化输出的公开类型名；`PHMDiagnosis`
保留为向后兼容别名（type alias），不破坏现有调用方。

### REQ-A-004 标识符/文件名领域无关
**THE SYSTEM SHALL** 重命名 `aircraft_prompts.py` → `profile_prompts.py` 及全部 importer；
`_extract_phm_diagnosis` → `_extract_structured_answer`；`_looks_like_phm_query` →
`_looks_like_domain_query`；`PHM_IDENTITY_RESPONSE` → `IDENTITY_RESPONSE`；
`SessionContext.prompt_profile` 默认值由 profile 派生（不硬编码 `phm_diagnosis_v1`）。

### REQ-A-005 标签后缀可配置
**THE** `prompt_profile_*` 标签后缀（`_diagnosis_v1`）**SHALL** 改为从 profile 派生
（`profile_suffix` 字段），不再对所有领域强制 `_diagnosis`。aviation profile 须通过
显式声明保留向后兼容的 `phm_diagnosis_v1` 值。

### REQ-A-006 启动日志去硬编码
**WHEN** 进程启动，**THE SYSTEM SHALL** 打印实际 active profile 的 label 与 sig，
不再硬编码 `PHM Prompt Profile: phm_diagnosis_v1`。

### REQ-A-007 前端领域无关
**THE** Web 前端欢迎语、快捷按钮、模式卡文案、profile label 映射**SHALL** 不硬编码
航空字面量；默认文案为领域无关。

### REQ-A-008 文档全量更新
**THE** 以下文档**SHALL** 反映全领域定位，删除「系统是航空 PHM 产品」的硬断言，
保留历史性/示例性航空引用：
- `README.md`（标题、概述、能力、`DOMAIN_PROFILE` 说明）
- `AGENTS.md`（架构概述、语言策略、prompt 单源、FMEA 默认）
- `core/AGENTS.md`、`agent/AGENTS.md`、`agent/skills/README.md`（prompt 单源路径）
- `docs/technical_report.md`（标题、概述、结构化输出、eval 节）
- `docs/API.md`（`StructuredAnswer` 契约、示例 payload 领域中性化）
- `docs/specs/prompts/README.md`、`docs/specs/prompts/critic.md`（FMEA 不绑定航空）

### REQ-A-009 测试矩阵
**THE SYSTEM SHALL** 提供单元 + 进程内 E2E 覆盖：
- `general` 默认启动、标签后缀、StructuredAnswer 抽取在 general 下返回 None、
  retrieve 启发式在 general 下不触发航空正则、fast_mode 兜底文案=profile、pii general 下无航空模式。
- 顶石 `test_e2e_domain_switch.py` 维持绿色。
- golden/snapshot 受影响项（prompt sig、标签格式）PR 单列 diff。

### REQ-A-010 向后兼容记录 [BREAKING]
**THE** `CHANGELOG.md [Unreleased]` **SHALL** 标 `[breaking]` 写明：
默认 profile 切换、`PHMDiagnosis`→`StructuredAnswer` 重命名（含别名）、
`aircraft_prompts.py`→`profile_prompts.py`（含旧 import 仍可用的兼容说明）。
