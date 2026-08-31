"""Typed retrieval-filter capabilities with fail-closed channel routing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum

__all__ = ["FilterCapability", "FilterKind", "FilterScope"]


class FilterKind(str, Enum):
    NONE = "none"
    SOURCE_SET = "source_set"
    MILVUS_EXPRESSION = "milvus_expression"
    INVALID = "invalid"


class FilterCapability(str, Enum):
    NONE = "none"
    SOURCE_SET = "source_set"
    MILVUS_EXPRESSION = "milvus_expression"


_SOURCE_EQ = re.compile(r"^\s*source\s*==\s*([\"'])(.*?)\1\s*$", re.IGNORECASE)
_SOURCE_IN = re.compile(r"^\s*source\s+in\s*\[(.*?)\]\s*$", re.IGNORECASE)
_QUOTED_VALUE = re.compile(r"([\"'])(.*?)\1")
_TRAILING_OPERATOR = re.compile(r"(?:==|!=|>=|<=|>|<|\bin\b|\band\b|\bor\b)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class FilterScope:
    """Parsed filter identity used to decide which channels may run.

    ``raw_expr`` remains request-local. Callers should expose only ``fingerprint``
    and ``kind`` in diagnostics.
    """

    kind: FilterKind
    raw_expr: str | None = None
    sources: frozenset[str] = frozenset()
    error_code: str | None = None

    @classmethod
    def parse(cls, expression: str | None) -> FilterScope:
        if expression is None or not expression.strip():
            return cls(FilterKind.NONE)
        raw = expression.strip()
        if len(raw) > 4096 or any(ord(char) < 32 for char in raw):
            return cls(FilterKind.INVALID, error_code="invalid_filter_syntax")

        equality = _SOURCE_EQ.fullmatch(raw)
        if equality:
            value = equality.group(2).strip()
            if value:
                return cls(FilterKind.SOURCE_SET, raw_expr=raw, sources=frozenset({value}))
            return cls(FilterKind.INVALID, error_code="invalid_filter_syntax")

        membership = _SOURCE_IN.fullmatch(raw)
        if membership:
            body = membership.group(1)
            values = [match.group(2).strip() for match in _QUOTED_VALUE.finditer(body)]
            # Reject unquoted or partially parsed list bodies rather than guessing.
            consumed = _QUOTED_VALUE.sub("", body)
            if values and not consumed.replace(",", "").strip() and all(values):
                return cls(
                    FilterKind.SOURCE_SET,
                    raw_expr=raw,
                    sources=frozenset(values),
                )
            return cls(FilterKind.INVALID, error_code="invalid_filter_syntax")

        if _TRAILING_OPERATOR.search(raw) or not re.search(r"(?:==|!=|>=|<=|>|<|\bin\b)", raw):
            return cls(FilterKind.INVALID, error_code="invalid_filter_syntax")
        return cls(FilterKind.MILVUS_EXPRESSION, raw_expr=raw)

    @property
    def fingerprint(self) -> str:
        if not self.raw_expr:
            return "none"
        return hashlib.sha256(self.raw_expr.encode("utf-8")).hexdigest()[:16]

    def supports(self, capability: FilterCapability) -> bool:
        if self.kind is FilterKind.INVALID:
            return False
        if self.kind is FilterKind.NONE:
            return True
        if capability is FilterCapability.MILVUS_EXPRESSION:
            return True
        if capability is FilterCapability.SOURCE_SET:
            return self.kind is FilterKind.SOURCE_SET
        return False

    def expression_for(self, capability: FilterCapability) -> str | None:
        return self.raw_expr if self.supports(capability) else None
