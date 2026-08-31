"""
Domain Prompts — 领域自适应 Prompt 向后兼容入口

所有常量从 active ``DomainProfile``(env ``DOMAIN_PROFILE`` 选择,默认 general)
派生。运行时读取请直接用 ``core.prompts.domain_profile.get_active_profile()``;
这些模块级常量仅用于 import 时求值的向后兼容。

切换领域:``DOMAIN_PROFILE=general``/``aviation_phm``(或其他 data/profiles/<name>.yaml)。
新增领域:在 data/profiles/ 下新增 yaml 即可,无需改代码。

事实来源:``core/prompts/domain_profile.py`` 的 ``DomainProfile`` +
``data/profiles/<name>.yaml``。
"""

from __future__ import annotations

from core.prompts.domain_profile import get_active_profile

__all__ = [
    "GENERAL_CHAT_SYSTEM_PROMPT",
    "IDENTITY_RESPONSE",
    "GENERATE_SYSTEM_PROMPT",
    "GENERATE_HUMAN_PROMPT",
    "REWRITE_PROMPT",
    "GRADE_SYSTEM_PROMPT",
    "GRADE_HUMAN_PROMPT",
    "PER_DOC_GRADE_SYSTEM_PROMPT",
    "PER_DOC_GRADE_HUMAN_PROMPT",
    "INTENT_CLASSIFICATION_PROMPT",
    "AGENT_SYSTEM_PROMPT",
    "RETRIEVER_TOOL_NAME",
    "RETRIEVER_TOOL_DESCRIPTION",
    "DEGRADATION_HELP_TEXT",
]


# 工具名是领域无关的常量(不随 profile 变)。
RETRIEVER_TOOL_NAME = "rag_retriever"


def _p():
    """Active profile accessor (kept tiny so each constant re-reads the
    cached profile — cheap, and lets tests that reset_active_profile() see
    the new profile without re-importing this module)."""
    return get_active_profile()


# ---------------------------------------------------------------------------
# 所有 prompt 常量从 active profile 派生(属性访问,每次取最新 active profile)。
# 用 module-level __getattr__ (PEP 562) 让 `from ... import GENERATE_SYSTEM_PROMPT`
# 在 import 时求值一次(向后兼容);运行时读取请用 get_active_profile() 直接访问。
# ---------------------------------------------------------------------------

# 注意:模块级常量在 import 时求值。对于测试中切换 profile 的场景,应直接用
# get_active_profile() 而非这些常量。下面在 import 时用 active profile 求值。

_profile = _p()

GENERAL_CHAT_SYSTEM_PROMPT = _profile.prompts["general_chat_system"]
IDENTITY_RESPONSE = _profile.identity_response
GENERATE_SYSTEM_PROMPT = _profile.prompts["generate_system"]
GENERATE_HUMAN_PROMPT = _profile.prompts["generate_human"]
REWRITE_PROMPT = _profile.prompts["rewrite"]
GRADE_SYSTEM_PROMPT = _profile.prompts["grade_system"]
GRADE_HUMAN_PROMPT = _profile.prompts["grade_human"]
PER_DOC_GRADE_SYSTEM_PROMPT = _profile.prompts["per_doc_grade_system"]
PER_DOC_GRADE_HUMAN_PROMPT = _profile.prompts["per_doc_grade_human"]
INTENT_CLASSIFICATION_PROMPT = _profile.prompts["intent"]
AGENT_SYSTEM_PROMPT = _profile.prompts["agent_system"]
RETRIEVER_TOOL_DESCRIPTION = _profile.retriever_tool_description
DEGRADATION_HELP_TEXT = _profile.degradation_help
