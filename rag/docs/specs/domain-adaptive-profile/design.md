# 领域自适应 DomainProfile — 设计

## 架构
```
data/profiles/<name>.yaml   ← 领域配置(单一事实来源)
        │ load_domain_profile(name)
        ▼
core/prompts/domain_profile.py  DomainProfile dataclass + 全局 active profile
        │ get_active_profile()
        ▼
所有消费者(input_guardrails / classifier / chat / skills / judge / ...)
```

## DomainProfile 字段
- `name`: profile id(如 `aviation_phm` / `general`)
- `display_name`: 人类可读名
- `prompts`: dict,含 generate_system / generate_human / general_chat_system / rewrite / grade_system / grade_human / intent / agent_system / hyde / entail
- `identity_response`: "你是谁" 文案
- `degradation_help`: 降级 help 文案
- `safety_disclaimer`: 安全免责
- `section_template`: 输出结构 section 列表(如 `["诊断结论",...]`),空列表=不强制结构
- `rag_keywords`: 意图+topic 关键词 list
- `chat_keywords`: 闲聊关键词 list
- `query_patterns`: 可选 regex list(如 ATA 编号模式)
- `refusal_message`: 拒答文案
- `empty_context_message`: 空知识库文案
- `retriever_tool_description`: 检索工具描述
- `pii_operational_patterns`: 可选 operational id 模式(默认空)

## 加载策略
- `get_active_profile()` 缓存;env `DOMAIN_PROFILE` 变更需重启(进程级)。
- YAML 缺字段时用 `general` 默认值填充(defensive)。
- 加载失败(文件缺失/解析错)→ log warning + 回退内置默认 profile(永不抛)。

## 向后兼容契约(关键)
- `aircraft_prompts.py` 保留所有原常量名(`GENERATE_SYSTEM_PROMPT` 等),改为 `get_active_profile().prompts["generate_system"]` 的属性访问。现有 `from core.prompts.aircraft_prompts import X` 全部继续工作。
- 默认 `DOMAIN_PROFILE=aviation_phm` → 行为零变化。
- profile 字符串 `phm_diagnosis_v1` 改为 `f"{profile.name}_diagnosis_v1"`(aviation_phm 下仍是 `aviation_phm_diagnosis_v1` —— **注意这是 breaking**,原值是 `phm_diagnosis_v1`)。为最小化影响,aviation_phm.yaml 里设 `profile_label: "phm"` 使 `phm_diagnosis_v1` 保持不变。

## 测试矩阵
- `tests/unit/test_domain_profile.py`:加载/回退/env/profile 字段完整性。
- `tests/e2e/test_e2e_domain_switch.py`:monkeypatch `DOMAIN_PROFILE=general` + 通用 mock 语料,断言非航空查询路由 RAG、不被拦、不强制 PHM 结构。
- 现有 431 测试全绿(默认 profile)。

## 不变量影响
- shared_state 键:无变化。
- 降级矩阵:无变化(profile 仅影响文案,不影响降级逻辑)。
- 熔断器:无变化。

## 安全影响
- input_guardrail 的 topic allow-list 从 profile 读;`general` profile 用空/通用关键词 → 不阻塞非航空输入。这是正向(解除领域锁定),但需确认不削弱注入防护(注入检测独立于 topic check,不受影响)。

## 回滚
- profile 层可独立删除;删除后 aircraft_prompts.py 回退硬编码。

## 风险(RISK,记录)
- 17 文件改动面广,每文件改动需小步 + 测试守护。
- `metadata.prompt_profile` breaking:在 CHANGELOG 标注 + 用 `profile_label` 保持 aviation 下旧值。
