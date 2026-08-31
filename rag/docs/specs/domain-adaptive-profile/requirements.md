# 领域自适应 DomainProfile — 需求

## 范围
把硬编码航空 PHM 的 RAG Agent 重构为**领域自适应**:通过 `DomainProfile`(YAML)切换领域,默认 `aviation_phm` 保持向后兼容,新增 `general` 通用 profile。目标:同一套代码 + harness 能服务任意知识库。

## 本质需求(ESSENTIAL)
- 领域相关的 prompts / keywords / 输出结构 / 身份文案 / 兜底提示 全部从 profile 读,源码不再出现领域字面量。
- 切换 `DOMAIN_PROFILE` env 即可换领域,无需改代码。
- 默认 `aviation_phm` 行为零变化(向后兼容契约)。

## 需求项(EARS)

- **REQ-D-001**: MUST 存在 `DomainProfile` dataclass + `load_domain_profile(name)` 加载器,从 `data/profiles/<name>.yaml` 读;env `DOMAIN_PROFILE`(默认 `aviation_phm`)选择 active profile;加载失败回退默认 profile。
- **REQ-D-002**: `aircraft_prompts.py` 的所有常量 MUST 改为从 active profile 派生(保留函数名做向后兼容 re-export)。
- **REQ-D-003**: `input_guardrails.py` 的 `_TOPIC_KEYWORDS` MUST 从 profile 读(最危险的 allow-list)。
- **REQ-D-004**: `classifier.py` 的 `_RAG_KEYWORDS`/`_CHAT_KEYWORDS` MUST 从 profile 读。
- **REQ-D-005**: `chat.py` 的 `_looks_like_phm_query`/`_extract_phm_diagnosis`/profile 字符串 MUST 从 profile 读。
- **REQ-D-006**: `output_guardrails.py`/`judge.py`/`memory/extractor.py`/`generate/skill.py`/`degradation.py`/`query_transform.py`/`retrieval_server.py` 的领域字面量 MUST 从 profile 读。
- **REQ-D-007**: MUST 提供 `data/profiles/aviation_phm.yaml`(完整外置)+ `data/profiles/general.yaml`(领域无关)。
- **REQ-D-008**: 默认 profile 下现有 431 测试 MUST 全绿(向后兼容)。
- **REQ-D-009**: `general` profile 下 MUST 能正确路由非航空查询(如"光合作用")走 RAG,不被 input_guardrail 拦、不强制 PHM 输出结构。

## Breaking change
- `metadata.prompt_profile` 值从固定 `phm_*` 变为 `<profile>_v1`(CHANGELOG `[breaking]` 标注)。
- 新增 env `DOMAIN_PROFILE`。
