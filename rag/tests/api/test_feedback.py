#!/usr/bin/env python3
"""
用户反馈接口测试

用法:
  python tests/api/test_feedback.py
"""

import json
import sys
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
    print("\n── 用户反馈接口测试 ──")

    # 1. Create session + send message to get a context
    print("\n  [准备会话]")
    status, body = _req("POST", "/api/chat", {"message": "测试反馈功能"}, timeout=60)
    if status != 200:
        print(f"  [SKIP] 无法创建会话 (HTTP {status})，跳过测试")
        sys.exit(0)
    session_id = body.get("session_id")
    assert_true("获取 session_id", session_id is not None)

    # 2. Submit thumbs up
    print("\n  [点赞反馈]")
    status, body = _req(
        "POST",
        "/api/feedback",
        {
            "session_id": session_id,
            "feedback_type": "THUMBS_UP",
        },
    )
    assert_ok("提交点赞返回 200", status, body)
    assert_true("返回 id", body.get("id") is not None, str(body))

    # 3. Submit thumbs down
    print("\n  [点踩反馈]")
    status, body = _req(
        "POST",
        "/api/feedback",
        {
            "session_id": session_id,
            "feedback_type": "THUMBS_DOWN",
            "content": "回答不够详细",
        },
    )
    assert_ok("提交点踩返回 200", status, body)

    # 4. Submit correction
    print("\n  [纠正反馈]")
    status, body = _req(
        "POST",
        "/api/feedback",
        {
            "session_id": session_id,
            "feedback_type": "CORRECTION",
            "original_answer": "git 默认分支名为 master",
            "corrected_answer": "git 默认分支名应为 main，参考官方文档",
        },
    )
    assert_ok("提交纠正返回 200", status, body)

    # 5. Submit flag
    print("\n  [标记反馈]")
    status, body = _req(
        "POST",
        "/api/feedback",
        {
            "session_id": session_id,
            "feedback_type": "FLAG",
            "content": "回答涉及不确定的安全操作",
        },
    )
    assert_ok("提交标记返回 200", status, body)

    # 6. Invalid feedback type
    print("\n  [异常参数]")
    status, body = _req(
        "POST",
        "/api/feedback",
        {
            "session_id": session_id,
            "feedback_type": "INVALID_TYPE",
        },
    )
    assert_ok("无效 feedback_type 返回 400", status, body, expected_status=400)

    # 7. Get session feedback
    print("\n  [获取会话反馈]")
    status, body = _req("GET", f"/api/feedback/{session_id}")
    assert_ok("GET /api/feedback/{session_id} 返回 200", status, body)
    if status == 200:
        feedback_list = body.get("feedback", [])
        assert_true("反馈数量 >= 4", len(feedback_list) >= 4, f"got: {len(feedback_list)}")

    # 8. Feedback stats
    print("\n  [反馈统计]")
    status, body = _req("GET", "/api/feedback/stats/summary")
    assert_ok("GET /api/feedback/stats/summary 返回 200", status, body)

    # 9. Pending escalations (admin)
    print("\n  [升级列表]")
    status, body = _req("GET", "/api/feedback/escalations/pending")
    assert_ok("GET /api/feedback/escalations/pending 返回 200", status, body)
    assert_true("pending 字段存在", "pending" in body, str(body))

    print(f"\n  {PASSED} passed, {FAILED} failed\n")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
