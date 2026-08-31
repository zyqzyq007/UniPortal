#!/usr/bin/env python3
"""
F09 — calculator AST safe-eval.

Replaces the legacy char-whitelist + ``eval()`` implementation. Verifies:
  - Legitimate arithmetic and whitelisted functions evaluate correctly.
  - ``abs``/``pow``/``min``/``max``/``round`` (previously unreachable under the
    char whitelist) now work.
  - Injection attempts (``__import__``, attribute access, dotted calls) are
    rejected with no code execution.

Run: pytest tests/unit/test_calculator.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")


class TestCalculatorLegitimate:
    @pytest.mark.parametrize(
        "expr,expected",
        [
            ("2*(3+4)", "14"),
            ("abs(-5)", "5"),
            ("pow(2,10)", "1024"),
            ("min(1,2)", "1"),
            ("max(3,4)", "4"),
            ("round(3.14159,2)", "3.14"),
            ("sqrt(16)", "4.0"),
            ("sin(0)", "0.0"),
        ],
    )
    def test_legitimate_expressions(self, expr, expected):
        from agent.mcp.tools_registry import UtilityToolsServer

        assert UtilityToolsServer.calculate(expr) == expected

    def test_empty_input_rejected(self):
        from agent.mcp.tools_registry import UtilityToolsServer

        assert "错误" in UtilityToolsServer.calculate("")
        assert "错误" in UtilityToolsServer.calculate(None)  # type: ignore[arg-type]


class TestCalculatorInjectionRejected:
    @pytest.mark.parametrize(
        "expr",
        [
            '__import__("os")',  # dunder import
            "(1).__class__",  # attribute access to class
            'os.system("ls")',  # dotted call (non-whitelisted name)
            "().__class__.__bases__",  # attribute chain
            'open("/etc/passwd")',  # non-whitelisted builtin
        ],
    )
    def test_injection_rejected_without_execution(self, expr):
        from agent.mcp.tools_registry import UtilityToolsServer

        result = UtilityToolsServer.calculate(expr)
        assert "错误" in result or "不允许" in result or "不支持" in result, (
            f"injection {expr!r} should be rejected, got {result!r}"
        )

    def test_syntax_error_rejected(self):
        from agent.mcp.tools_registry import UtilityToolsServer

        assert "错误" in UtilityToolsServer.calculate("2 +* 3")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
