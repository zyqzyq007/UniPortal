#!/usr/bin/env python3
"""
对话接口测试 — 非流式 + SSE 流式

用法:
  python tests/api/test_chat.py
"""

import http.client
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000"

PASSED = 0
FAILED = 0


def _req(method, path, data=None, timeout=60):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url, data=body, method=method, headers={"Content-Type": "application/json"} if body else {}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
    except Exception as e:
        return 0, {"error": str(e)}


def assert_ok(name, status, body, expected_status=200):
    global PASSED, FAILED
    if status == expected_status:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name}  (HTTP {status}) {body}")


def assert_true(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name}  {detail}")


def test_general_chat():
    """通用闲聊 — 不走 RAG"""
    print("\n  [非流式] 通用闲聊")

    status, body = _req(
        "POST",
        "/api/chat",
        {
            "message": "你好，请介绍一下你自己",
            "stream": False,
        },
        timeout=30,
    )
    assert_ok("通用闲聊返回 200", status, body)
    if status == 200:
        assert_true("回答非空", len(body.get("response", "")) > 0)
        assert_true("包含 session_id", body.get("session_id") is not None)

    return body.get("session_id")


def test_rag_chat(session_id):
    """RAG 知识库检索问答"""
    print("\n  [非流式] RAG 问答")

    status, body = _req(
        "POST",
        "/api/chat",
        {
            "message": "git 合并冲突如何解决？",
            "session_id": session_id,
            "stream": False,
            "mode": "thinking",
        },
        timeout=120,
    )
    assert_ok("RAG 问答返回 200", status, body)
    if status == 200:
        answer = body.get("response", "")
        assert_true("回答非空", len(answer) > 0, f"length: {len(answer)}")
        print(f"    → {answer[:100]}...")


def test_fast_mode_chat(session_id):
    """快速模式对话"""
    print("\n  [非流式] 快速模式")

    status, body = _req(
        "POST",
        "/api/chat",
        {
            "message": "docker 部署的常用命令？",
            "session_id": session_id,
            "mode": "fast",
        },
        timeout=60,
    )
    assert_ok("快速模式返回 200", status, body)
    if status == 200:
        assert_true(
            "route == fast",
            body.get("metadata", {}).get("route") == "fast",
            f"got: {body.get('metadata', {}).get('route')}",
        )


def test_sse_stream(session_id):
    """SSE 流式对话"""
    print("\n  [流式] SSE 对话")

    conn = http.client.HTTPConnection("localhost", 8000, timeout=60)
    body = json.dumps(
        {
            "message": "git 合并冲突如何解决？",
            "session_id": session_id,
            "stream": True,
        }
    ).encode()
    conn.request(
        "POST", "/api/chat/stream", body=body, headers={"Content-Type": "application/json"}
    )

    resp = conn.getresponse()
    assert_true("SSE 响应状态 200", resp.status == 200, f"got: {resp.status}")

    raw = resp.read().decode()
    events = [line for line in raw.split("\n") if line.startswith("data: ")]

    event_types = []
    for line in events:
        try:
            event_types.append(json.loads(line[6:])["type"])
        except Exception:
            pass

    assert_true("包含 session 事件", "session" in event_types, f"events: {event_types}")
    assert_true("包含 intent 事件", "intent" in event_types, f"events: {event_types}")
    assert_true("包含 token 事件", "token" in event_types, f"events: {event_types}")
    assert_true("包含 done 事件", "done" in event_types, f"events: {event_types}")
    conn.close()


def test_prompt_status():
    """Prompt 状态查询"""
    print("\n  [Prompt 状态]")

    status, body = _req("GET", "/api/chat/prompt-status")
    assert_ok("GET /api/chat/prompt-status 返回 200", status, body)
    if status == 200:
        assert_true("loaded == true", body.get("loaded") is True)
        assert_true("prompt_profile 非空", len(body.get("prompt_profile", "")) > 0)


def main():
    print("\n── 对话接口测试 ──")

    status, _ = _req("GET", "/health", timeout=5)
    if status != 200:
        print(f"\n  [FAIL] 后端未运行 (GET /health -> {status})")
        sys.exit(1)

    session_id = test_general_chat()
    test_rag_chat(session_id)
    test_fast_mode_chat(session_id)
    test_sse_stream(session_id)
    test_prompt_status()

    print(f"\n  {PASSED} passed, {FAILED} failed\n")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
