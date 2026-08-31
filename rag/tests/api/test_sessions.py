#!/usr/bin/env python3
"""
会话管理接口测试

用法:
  python tests/api/test_sessions.py
"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000"

PASSED = 0
FAILED = 0


def _req(method, path, data=None, timeout=30):
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


def main():
    print("\n── 会话管理接口测试 ──")

    # 1. Create session
    print("\n  [创建会话]")
    status, body = _req("POST", "/api/sessions")
    assert_ok("POST /api/sessions 返回 200", status, body)
    session_id = body.get("session_id")
    assert_true("返回 session_id", session_id is not None, str(body))

    # 2. Send a message to create history
    print("\n  [发送消息建立历史]")
    status, body = _req(
        "POST",
        "/api/chat",
        {
            "message": "测试会话消息",
            "session_id": session_id,
        },
        timeout=60,
    )
    assert_ok("发送消息返回 200", status, body)

    # 3. List sessions
    print("\n  [会话列表]")
    status, body = _req("GET", "/api/sessions")
    assert_ok("GET /api/sessions 返回 200", status, body)
    assert_true("total >= 1", body.get("total", 0) >= 1, f"got: {body.get('total')}")

    # 4. Get session detail
    print("\n  [会话详情]")
    status, body = _req("GET", f"/api/sessions/{session_id}")
    assert_ok("GET /api/sessions/{id} 返回 200", status, body)
    assert_true(
        "session_id 匹配", body.get("session_id") == session_id, f"got: {body.get('session_id')}"
    )

    # 5. Get chat history
    print("\n  [对话历史]")
    status, body = _req("GET", f"/api/chat/history/{session_id}?limit=10")
    assert_ok("GET /api/chat/history 返回 200", status, body)
    assert_true(
        "total_messages >= 2",
        body.get("total_messages", 0) >= 2,
        f"got: {body.get('total_messages')}",
    )

    # 6. Extend session
    print("\n  [延长会话有效期]")
    status, body = _req("POST", f"/api/sessions/{session_id}/extend")
    assert_ok("POST extend 返回 200", status, body)

    # 7. Delete session
    print("\n  [删除会话]")
    status, body = _req("DELETE", f"/api/sessions/{session_id}")
    assert_ok("DELETE /api/sessions/{id} 返回 200", status, body)

    # 8. Verify deletion
    status, body = _req("GET", f"/api/sessions/{session_id}")
    assert_ok("删除后查询返回 404", status, body, expected_status=404)

    print(f"\n  {PASSED} passed, {FAILED} failed\n")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
