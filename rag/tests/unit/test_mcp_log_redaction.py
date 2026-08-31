from __future__ import annotations

import asyncio

from loguru import logger


def _capture_logs():
    records: list[str] = []
    handler = logger.add(
        lambda message: records.append(str(message)), level="DEBUG", format="{message}"
    )
    return records, handler


def test_mcp_success_log_does_not_contain_argument_values() -> None:
    from agent.mcp.server import InProcessMCPServer

    canary = "query-secret-canary-4f9321"
    server = InProcessMCPServer()
    server.register_tool(
        "fixture",
        "fixture",
        {"type": "object", "properties": {"query": {"type": "string"}}},
        lambda query: {"length": len(query)},
    )
    records, handler = _capture_logs()
    try:
        result = asyncio.run(server.call_tool("fixture", {"query": canary}))
    finally:
        logger.remove(handler)

    assert result.success is True
    assert canary not in "\n".join(records)
    assert "query" in "\n".join(records)


def test_mcp_failure_log_and_result_do_not_echo_exception_secret() -> None:
    from agent.mcp.server import InProcessMCPServer

    canary = "url-token-canary-8ab211"

    def _fail(url: str) -> None:
        raise ValueError(f"failed URL {url}")

    server = InProcessMCPServer()
    server.register_tool(
        "fixture",
        "fixture",
        {"type": "object", "properties": {"url": {"type": "string"}}},
        _fail,
    )
    records, handler = _capture_logs()
    try:
        result = asyncio.run(server.call_tool("fixture", {"url": canary}))
    finally:
        logger.remove(handler)

    assert result.success is False
    assert canary not in "\n".join(records)
    assert canary not in (result.error or "")
    assert "ValueError" in (result.error or "")


def test_retrieval_mcp_source_never_logs_query_or_raw_exception() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    source = (root / "agent" / "mcp" / "retrieval_server.py").read_text(encoding="utf-8")
    assert "query[:" not in source
    assert not any(rethrow in source for rethrow in (": {e}", ": {exc}", "{str(e)}", "{str(exc)}"))


def test_mcp_retrieval_call_chain_has_no_explicit_query_snippet_logs() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    runtime_sources = (
        "agent/skills/retrieve/skill.py",
        "core/intent/classifier.py",
        "core/retrieval/query_transform.py",
        "documents/milvus_db.py",
    )
    for relative in runtime_sources:
        source = (root / relative).read_text(encoding="utf-8")
        log_calls = "\n".join(line for line in source.splitlines() if "log." in line)
        assert not any(
            snippet in log_calls
            for snippet in ("query[:", "q[:30]", "query='{query", "for: {query")
        ), relative
