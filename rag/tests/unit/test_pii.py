#!/usr/bin/env python3
"""
F08 — PII classification tiers + opt-in LLM pass degradation.

  - Human PII (id_card/phone/bank/email/ip/passport) is detected by default.
  - Operational identifiers (tail_number/msn) are NOT human PII — they are
    optional operational content, sourced solely from the active domain profile
    and gated behind PII_DETECT_OPERATIONAL_IDS (default off). No built-in
    domain regex fallback exists: a profile that does not declare operational
    patterns inherits none (domain-generalization REQ-DG-001/002/003).
  - The opt-in LLM pass degrades to regex-only when the judge is unavailable
    (unavailable != "PII found" != "no PII"), and never raises.

Run: pytest tests/unit/test_pii.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")


class TestOperationalIDsNoBuiltInFallback:
    """REQ-DG-001/002/003 — no built-in domain regex fallback.

    Operational patterns come ONLY from the active profile's
    ``pii_operational_patterns``. A profile that omits the key must NOT inherit
    any built-in aviation regex (the legacy fallback that coupled the generic
    platform to a specific domain has been removed). This is a breaking change
    for third-party profiles that relied on the implicit fallback.
    """

    def test_undeclared_profile_inherits_no_operational_patterns(self, monkeypatch, tmp_path):
        """A profile whose YAML omits ``pii_operational_patterns`` entirely must
        yield NO operational patterns even when PII_DETECT_OPERATIONAL_IDS is on.
        Critic F-C4 / Defender F-01 — the legacy built-in fallback is removed."""
        from agent.guardrails import pii as pii_mod
        from core.prompts import domain_profile as dp_mod
        from core.prompts.domain_profile import reset_active_profile

        # Write a third-party-style profile YAML that omits the operational key.
        (tmp_path / "undeclared_domain.yaml").write_text(
            "name: undeclared_domain\nprofile_label: undeclared\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(dp_mod, "PROFILES_DIR", tmp_path)

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "undeclared_domain")
        monkeypatch.setenv("PII_DETECT_OPERATIONAL_IDS", "true")

        text = "对 B-1234 号机进行检查，参考 MSN 12345"
        matches = pii_mod.detect_pii(text)
        kinds = {m.kind for m in matches}
        assert "tail_number" not in kinds
        assert "msn" not in kinds
        reset_active_profile()

    def test_human_pii_still_detected_without_operational(self, monkeypatch, tmp_path):
        """Removing the operational fallback MUST NOT touch human PII detection.
        Critic F-C4 verification (b): PII_PATTERNS stays intact."""
        from agent.guardrails import pii as pii_mod
        from core.prompts import domain_profile as dp_mod
        from core.prompts.domain_profile import reset_active_profile

        (tmp_path / "undeclared_domain.yaml").write_text(
            "name: undeclared_domain\nprofile_label: undeclared\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(dp_mod, "PROFILES_DIR", tmp_path)

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "undeclared_domain")
        # Human PII (id_card) detected regardless of operational-id opt-in.
        assert any(
            m.kind == "id_card" for m in pii_mod.detect_pii("身份证号 110101199003073814 请登记")
        )
        reset_active_profile()

    def test_no_module_level_operational_constant(self):
        """REQ-DG-002 — the module MUST NOT define a built-in operational
        patterns constant. Detection is profile-sourced only."""
        from agent.guardrails import pii as pii_mod

        assert not hasattr(pii_mod, "_OPERATIONAL_PATTERNS"), (
            "pii.py must not ship a built-in _OPERATIONAL_PATTERNS constant; "
            "operational patterns come solely from the active domain profile."
        )


class TestHumanPIIDefault:
    def test_passport_detected(self):
        from agent.guardrails.pii import detect_pii

        matches = [m for m in detect_pii("护照号 E12345678 请登记") if m.kind == "passport"]
        assert matches and matches[0].value == "E12345678"

    def test_phone_still_detected(self):
        from agent.guardrails.pii import detect_pii

        assert any(m.kind == "phone" for m in detect_pii("电话 13812345678"))


class TestOperationalIDsDefaultOff:
    def test_tail_number_not_detected_by_default(self):
        """Aircraft tail numbers are operational content, not human PII — must
        NOT be redacted by default (would mangle domain content)."""
        from agent.guardrails.pii import detect_pii

        text = "对 B-1234 号机进行起落架检查，参考 MSN 12345 的维修记录"
        matches = detect_pii(text)
        kinds = {m.kind for m in matches}
        assert "tail_number" not in kinds
        assert "msn" not in kinds

    def test_tail_number_detected_when_opted_in(self, monkeypatch):
        """Operational-id detection is profile-gated. The aviation profile
        supplies tail_number/MSN patterns; general does not. [REQ-A-002]"""
        from agent.guardrails import pii as pii_mod
        from core.prompts.domain_profile import reset_active_profile

        # Aviation profile defines tail_number/MSN operational patterns.
        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "aviation_phm")
        monkeypatch.setenv("PII_DETECT_OPERATIONAL_IDS", "true")
        text = "对 B-1234 号机进行检查"
        matches = pii_mod.detect_pii(text)
        assert any(m.kind == "tail_number" for m in matches)

        # General profile explicitly declares none — even when opted in.
        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "general")
        pii_mod._operational_patterns_from_profile  # warm import
        assert not any(m.kind == "tail_number" for m in pii_mod.detect_pii(text))


class TestLLMPassDegradesGracefully:
    def test_llm_pass_off_by_default_returns_regex_only(self, monkeypatch):
        from agent.guardrails.pii import detect_pii_with_llm

        # No regex hit, LLM pass off -> empty.
        assert detect_pii_with_llm("发动机振动异常") == []

    def test_llm_pass_degrades_when_judge_unavailable(self, monkeypatch):
        """When PII_LLM_PASS is on but the judge breaker is tripped / unavailable,
        the LLM pass returns regex-only results and never raises."""
        from agent.guardrails import pii as pii_mod

        monkeypatch.setenv("PII_LLM_PASS", "true")

        class _DeadJudge:
            available = False

            def _ask(self, prompt):
                raise AssertionError("judge must not be called when unavailable")

        import agent.eval.judge as judge_mod

        monkeypatch.setattr(judge_mod, "get_judge", lambda: _DeadJudge())

        # No regex hit, LLM unavailable -> empty (NOT "PII found").
        assert pii_mod.detect_pii_with_llm("一些不含正则PII的普通文本") == []

    def test_llm_pass_never_raises_on_exception(self, monkeypatch):
        from agent.guardrails import pii as pii_mod

        monkeypatch.setenv("PII_LLM_PASS", "true")

        import agent.eval.judge as judge_mod

        monkeypatch.setattr(
            judge_mod, "get_judge", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        )

        # Must not propagate.
        result = pii_mod.detect_pii_with_llm("普通文本")
        assert result == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
