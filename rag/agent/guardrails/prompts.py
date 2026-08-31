from __future__ import annotations

import re


def _safety_disclaimer() -> str:
    """Safety disclaimer sourced from the active domain profile."""
    from core.prompts.domain_profile import get_active_profile

    return get_active_profile().safety_disclaimer


# Safety disclaimer appended to answers (domain-adaptive via the profile).
SAFETY_DISCLAIMER = _safety_disclaimer()

# ---------------------------------------------------------------------------
# Compiled regex patterns for prompt-injection detection
# ---------------------------------------------------------------------------
INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+(instructions|prompts|rules)", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?above", re.IGNORECASE),
    re.compile(
        r"disregard\s+(all\s+)?(previous|above|prior)\s+(instructions|rules|prompts)", re.IGNORECASE
    ),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"\bDAN\b"),
    re.compile(r"<\s*script", re.IGNORECASE),
    re.compile(r"```\s*(system|assistant|user)\s*:", re.IGNORECASE),
    re.compile(r"pretend\s+(you\s+are|to\s+be)\s+a", re.IGNORECASE),
    re.compile(r"act\s+as\s+(if\s+you\s+(are|were)\s+)?a", re.IGNORECASE),
    re.compile(r"override\s+(your|the)\s+(instructions|rules|guidelines)", re.IGNORECASE),
    re.compile(
        r"reveal\s+(your|the)\s+(system|hidden|internal)\s+(prompt|instructions|rules)",
        re.IGNORECASE,
    ),
    # --- Chinese (the primary user base is Chinese-language) ---
    re.compile(
        r"忽略(以上|前面|之前|上面|先前)(的)?(所有|全部)?(指令|规则|提示|提示词|内容|要求|设定)"
    ),
    re.compile(r"无视(以上|前面|之前|上面|先前)(的)?(所有|全部)?(指令|规则|提示|内容|要求|设定)"),
    re.compile(
        r"不要(遵守|理会|执行|遵循)(以上|前面|之前|上面|系统|任何)(的)?(指令|规则|提示|限制)"
    ),
    re.compile(r"你现在是(一个)?(DAN|开发者模式|无限制|无限制模式|越狱|管理员)"),
    re.compile(r"进入(开发者|越狱|无限制|DAN|root|admin).{0,4}模式"),
    re.compile(r"越狱"),
    re.compile(
        r"(扮演|假装|模拟)(成|为|是)?(一个)?(DAN|没有限制|不受限|无道德|越狱).{0,6}(AI|助手|模型|角色|身份)"
    ),
    re.compile(
        r"(输出|打印|显示|告诉我|给出|展示)(你的|系统的|真实的)?(系统|内部|隐藏|真实|初始)(的)?(提示词|提示|指令|规则|prompt|设定)"
    ),
    re.compile(r"取消(所有|全部)?(限制|安全|道德)(限制|策略|规则)?"),
]
