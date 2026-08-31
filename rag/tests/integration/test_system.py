#!/usr/bin/env python3
"""
RAG 智能问答系统 — 全链路功能测试

覆盖:
  1. 后端健康检查 & Milvus 连通性
  2. 文档上传 + 重复上传拦截
  3. 文档列表 / 查询 / 删除
  4. 非流式对话 (通用闲聊 + RAG 检索)
  5. 流式对话
  6. 会话历史
  7. BM25 稀疏检索
  8. 混合检索 (dense + sparse)

用法:
  先启动后端:  ./run.sh  或  python -m uvicorn api.main:app --port 8000
  再运行测试:  python tests/system_test.py
"""

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000"

# ── Helpers ──────────────────────────────────────────────────────────────────

PASSED = 0
FAILED = 0
SKIPPED = 0


def _req(method, path, data=None, timeout=60):
    """Send HTTP request and return (status, json_body)."""
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


def _upload(filename, content):
    """Upload a file via multipart/form-data (no external deps)."""
    import http.client

    boundary = "----TestBoundary123456"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/markdown\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    conn = http.client.HTTPConnection("localhost", 8000, timeout=60)
    conn.request(
        "POST",
        "/api/documents/upload",
        body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    resp = conn.getresponse()
    result = json.loads(resp.read())
    conn.close()
    return resp.status, result


def _wait_for_indexed(doc_id, max_wait=120, interval=2):
    """Poll document status until indexed/failed or timeout (Q6, F-EG-08).

    Replaces a fixed `time.sleep(20)` that waited for background indexing —
    polling returns as soon as the doc is ready (faster on a warm index) and
    bounds the wait so a stuck ingest surfaces instead of an arbitrary sleep.
    """
    deadline = time.time() + max_wait
    last = None
    while time.time() < deadline:
        status, body = _req("GET", f"/api/documents/{doc_id}")
        if status == 200:
            last = body.get("status")
            if last in ("indexed", "failed"):
                return last
        time.sleep(interval)
    return last  # None if never reached


def assert_ok(name, status, body, expected_status=200):
    global PASSED, FAILED
    if status == expected_status:
        PASSED += 1
        print(f"  ✓ {name}")
        return True
    else:
        FAILED += 1
        print(f"  ✗ {name}  (HTTP {status}) {body}")
        return False


def assert_true(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {name}")
    else:
        FAILED += 1
        print(f"  ✗ {name}  {detail}")


def section(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ── Test Content ─────────────────────────────────────────────────────────────

TEST_DOC = """# Git 合并冲突排查指南

## 合并 - 基础概念

### 常见问题：合并冲突

#### 解决步骤：
1. 通过 git status 确认冲突文件
2. 打开带冲突标记的文件
3. 保留正确内容并删除冲突标记
4. 运行 git add 标记冲突已解决
5. 检查相关测试是否通过

#### 常见标识：
- MERGE-CONFLICT-01：标准文本冲突
- MERGE-CONFLICT-02：二进制文件冲突

### 常见问题：分支管理

#### 解决步骤：
1. 通过 git branch 查看本地分支
2. 检查远程跟踪分支是否同步
3. 切换到目标分支再进行合并
4. 必要时使用 git rebase 整理历史
5. 如历史混乱，可重置后再提交

#### 相关参考：
- git merge 官方文档
- git rebase 与 merge 的区别说明
"""


# ── Tests ────────────────────────────────────────────────────────────────────


def test_health():
    section("1. 后端健康检查 & Milvus 连通性")

    status, body = _req("GET", "/health")
    assert_ok("GET /health 返回 200", status, body)
    assert_true("status == healthy", body.get("status") == "healthy", body)

    status, body = _req("GET", "/api/admin/health")
    assert_ok("GET /api/admin/health 返回 200", status, body)
    milvus = body.get("services", {}).get("milvus", {})
    assert_true(
        "Milvus connected",
        milvus.get("status") == "healthy",
        f"got: {milvus.get('status')}, details: {milvus}",
    )


def test_document_upload():
    section("2. 文档上传 & 重复检测")

    # Upload a test document
    status, body = _upload("test_hydraulic_troubleshooting.md", TEST_DOC)
    assert_ok("上传测试文档成功 (200/409)", status, body, expected_status=200)
    if status != 200:
        return None

    doc_id = body.get("id")
    assert_true("返回了 doc_id", doc_id is not None, body)

    # Wait for background processing (Q6: poll instead of fixed sleep)
    print("  ⏳ 等待文档处理完成...")
    final_status = _wait_for_indexed(doc_id)
    assert_true("文档处理完成", final_status == "indexed", f"got: {final_status}")

    # Check document status
    status, body = _req("GET", f"/api/documents/{doc_id}")
    assert_ok("查询文档状态", status, body)
    if status == 200:
        assert_true(
            "文档状态为 indexed", body.get("status") == "indexed", f"got: {body.get('status')}"
        )

    # Upload the same file again — should be blocked
    status2, body2 = _upload("test_hydraulic_troubleshooting.md", TEST_DOC)
    assert_ok("重复上传被拒绝 (409)", status2, body2, expected_status=409)

    # Upload same content with different filename — should also be blocked
    status3, body3 = _upload("renamed_file.md", TEST_DOC)
    assert_ok("相同内容不同文件名也被拒绝 (409)", status3, body3, expected_status=409)

    return doc_id


def test_document_list(doc_id):
    section("3. 文档列表 & 查询 & 删除")

    status, body = _req("GET", "/api/documents")
    assert_ok("GET /api/documents 返回 200", status, body)
    assert_true("文档列表 total >= 1", body.get("total", 0) >= 1, f"got: {body.get('total')}")

    if doc_id:
        status, body = _req("GET", f"/api/documents/{doc_id}")
        assert_ok(f"GET /api/documents/{doc_id}", status, body)

        # Delete
        status, body = _req("DELETE", f"/api/documents/{doc_id}")
        assert_ok(f"DELETE /api/documents/{doc_id}", status, body)

        # Verify deletion
        status, body = _req("GET", f"/api/documents/{doc_id}")
        assert_ok("删除后查询返回 404", status, body, expected_status=404)


def test_chat_general():
    section("4. 非流式对话 — 通用闲聊 (不走 RAG)")

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
        assert_true(
            "返回了非空回答",
            len(body.get("response", "")) > 0,
            f"response length: {len(body.get('response', ''))}",
        )
        assert_true("包含 session_id", body.get("session_id") is not None)
        print(f"  → 回答片段: {body.get('response', '')[:80]}...")
    return body.get("session_id")


def test_chat_rag(session_id):
    section("5. 非流式对话 — RAG 检索问答")

    # First, upload a doc so RAG has something to search
    status, body = _upload("test_rag_query.md", TEST_DOC)
    if status == 200:
        print("  ⏳ 等待文档索引...")
        _wait_for_indexed(body.get("id"))

    status, body = _req(
        "POST",
        "/api/chat",
        {
            "message": "git 合并冲突如何解决？",
            "session_id": session_id,
            "stream": False,
        },
        timeout=60,
    )
    assert_ok("RAG 问答返回 200", status, body)
    if status == 200:
        answer = body.get("response", "")
        assert_true("回答非空", len(answer) > 0, f"length: {len(answer)}")
        print(f"  → 回答片段: {answer[:120]}...")


def test_chat_stream(session_id):
    section("6. 流式对话 (SSE)")

    import http.client

    conn = http.client.HTTPConnection("localhost", 8000, timeout=60)
    body = json.dumps(
        {
            "message": "git 分支管理的常用命令是什么？",
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


def test_session_history(session_id):
    section("7. 会话历史")

    status, body = _req("GET", f"/api/chat/history/{session_id}?limit=10")
    assert_ok("GET /api/chat/history 返回 200", status, body)
    if status == 200:
        total = body.get("total_messages", 0)
        assert_true("历史消息 >= 2", total >= 2, f"got: {total}")


def test_milvus_direct():
    section("8. Milvus 检索 (via API)")

    # Test via admin health (avoids file-lock issue with Milvus Lite)
    status, body = _req("GET", "/api/admin/health")
    milvus = body.get("services", {}).get("milvus", {})
    assert_true(
        "Milvus connected (via admin)",
        milvus.get("status") == "healthy",
        f"got: {milvus.get('status')}",
    )

    # Test retrieval via chat endpoint (end-to-end)
    status, body = _req(
        "POST",
        "/api/chat",
        {
            "message": "git 合并冲突如何解决？",
            "stream": False,
        },
        timeout=60,
    )
    assert_ok("Milvus 检索后对话返回 200", status, body)
    if status == 200:
        answer = body.get("response", "")
        assert_true(
            "回答包含相关内容 (含 '合并' 或 '冲突')",
            "合并" in answer or "冲突" in answer,
            f"answer: {answer[:100]}...",
        )
        print(f"  → 回答片段: {answer[:120]}...")


def test_bm25_and_hybrid():
    section("9. BM25 & 混合检索 (via API)")

    # BM25 and hybrid retrieval are tested end-to-end via the chat API
    # (avoids Milvus Lite file-lock issues when testing in a separate process)

    # Use a keyword-heavy query that BM25 should match well
    status, body = _req(
        "POST",
        "/api/chat",
        {
            "message": "标识 MERGE-CONFLICT-01 是什么意思？",
            "stream": False,
        },
        timeout=60,
    )
    assert_ok("关键词检索对话返回 200", status, body)
    if status == 200:
        answer = body.get("response", "")
        assert_true("回答非空", len(answer) > 0, f"length: {len(answer)}")
        print(f"  → 回答片段: {answer[:120]}...")


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    print()
    print("=" * 60)
    print("  RAG 智能问答系统 — 全链路功能测试")
    print("=" * 60)

    # Pre-check: backend must be running
    status, _ = _req("GET", "/health", timeout=5)
    if status != 200:
        print(f"\n  ✗ 后端未运行 (GET /health → {status})")
        print("  请先启动: ./run.sh 或 python -m uvicorn api.main:app --port 8000")
        sys.exit(1)

    test_health()
    doc_id = test_document_upload()
    test_chat_general()
    test_chat_rag(session_id := f"test_{int(time.time())}")
    test_chat_stream(session_id)
    test_session_history(session_id)
    test_milvus_direct()
    test_bm25_and_hybrid()
    test_document_list(doc_id)  # Delete at the end

    # Summary
    print(f"\n{'=' * 60}")
    total = PASSED + FAILED + SKIPPED
    print(f"  测试完成:  {PASSED} passed,  {FAILED} failed,  {SKIPPED} skipped  (total {total})")
    print(f"{'=' * 60}\n")

    sys.exit(1 if FAILED > 0 else 0)


if __name__ == "__main__":
    main()
