# 领域自适应 DomainProfile — 任务清单

- [ ] [REQ-D-001] 新增 `core/prompts/domain_profile.py`:DomainProfile dataclass + load_domain_profile + get_active_profile(含 env/回退)
- [ ] [REQ-D-007] 新增 `data/profiles/aviation_phm.yaml`(完整外置现有内容,profile_label=phm)+ `data/profiles/general.yaml`
- [ ] [REQ-D-002] `aircraft_prompts.py` 改为从 active profile 派生(保留常量名兼容)
- [ ] [REQ-D-003] `input_guardrails.py` _TOPIC_KEYWORDS 从 profile 读
- [ ] [REQ-D-004] `classifier.py` _RAG_KEYWORDS/_CHAT_KEYWORDS 从 profile 读
- [ ] [REQ-D-005] `chat.py` _looks_like_phm_query/_extract_phm_diagnosis/profile 字符串从 profile 读
- [ ] [REQ-D-006] output_guardrails / judge / memory extractor / generate skill / degradation / query_transform / retrieval_server 领域字面量从 profile 读
- [ ] [REQ-D-008] 现有 431 测试全绿(默认 aviation_phm)
- [ ] [REQ-D-009] `tests/unit/test_domain_profile.py` + `tests/e2e/test_e2e_domain_switch.py`(general profile 非航空查询)
- [ ] critic/defender 评审,归档 review/{critic,defender,tracking}.md
- [ ] CHANGELOG [breaking] 标注 metadata.prompt_profile
