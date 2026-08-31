#!/usr/bin/env python3
"""
知识库检索接口测试 — 混合 / 纯向量 / 纯 BM25

用法:
  python tests/api/test_retrieval.py

注意: 运行前需要先上传文档（可运行 test_documents.py 或直接上传）
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

TEST_DOC = """# Git 合并冲突排查指南

## 合并 - 基础概念

### 常见问题：合并冲突

#### 解决步骤：
1. 通过 git status 确认冲突文件
2. 打开带冲突标记的文件
3. 保留正确内容并删除冲突标记
4. 运行 git add 标记冲突已解决
5. 执行 git commit 完成合并提交

#### 常见标识：
- MERGE-CONFLICT-01：标准文本冲突
- MERGE-CONFLICT-02：二进制文件冲突

#### 相关参考：
- git merge 官方文档
- git rebase 与 merge 的区别说明
"""


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


def _upload(filename, content):
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
    """Poll document status until indexed/failed or timeout (Q6, F-EG-08)."""
    deadline = time.time() + max_wait
    last = None
    while time.time() < deadline:
        status, body = _req("GET", f"/api/documents/{doc_id}")
        if status == 200:
            last = body.get("status")
            if last in ("indexed", "failed"):
                return last
        time.sleep(interval)
    return last


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


def ensure_document_indexed():
    """确保测试文档已上传并索引。"""
    status, body = _req("GET", "/api/documents")
    if status == 200 and body.get("total", 0) > 0:
        print("  知识库已有文档，跳过上传")
        return None

    print("  上传测试文档到知识库...")
    status, body = _upload("test_retrieval_git.md", TEST_DOC)
    if status in (200, 409):
        print("  等待索引完成...")
        if status == 200 and body.get("id"):
            _wait_for_indexed(body["id"])
        return body.get("id") if status == 200 else None
    return None


def test_hybrid():
    """混合检索 (dense + BM25 + RRF)"""
    print("\n  [混合检索] POST /api/retrieval")

    status, body = _req(
        "POST",
        "/api/retrieval",
        {
            "query": "git 合并冲突如何解决",
            "top_k": 5,
        },
    )
    assert_ok("返回 200", status, body)
    if status == 200:
        assert_true("results 是列表", isinstance(body.get("results"), list))
        assert_true("query 回显正确", body.get("query") == "git 合并冲突如何解决")
        assert_true("total 字段存在", "total" in body)
        assert_true("retrieval_time_ms > 0", body.get("retrieval_time_ms", 0) > 0)
        if body["results"]:
            r = body["results"][0]
            assert_true("result 包含 content", "content" in r)
            assert_true("result 包含 score", "score" in r)
            print(f"    → 命中 {body['total']} 条, 耗时 {body['retrieval_time_ms']:.1f}ms")
            print(f"    → Top1 score={r['score']:.4f}, source={r.get('source', '')}")


def test_dense():
    """纯向量检索"""
    print("\n  [纯向量检索] POST /api/retrieval/dense")

    status, body = _req(
        "POST",
        "/api/retrieval/dense",
        {
            "query": "git 合并冲突如何解决",
            "top_k": 5,
        },
    )
    assert_ok("返回 200", status, body)
    if status == 200:
        assert_true("results 是列表", isinstance(body.get("results"), list))
        if body["results"]:
            print(f"    → 命中 {body['total']} 条, 耗时 {body['retrieval_time_ms']:.1f}ms")


def test_sparse():
    """纯 BM25 关键词检索"""
    print("\n  [纯关键词检索] POST /api/retrieval/sparse")

    status, body = _req(
        "POST",
        "/api/retrieval/sparse",
        {
            "query": "MERGE-CONFLICT-01 冲突",
            "top_k": 5,
        },
    )
    assert_ok("返回 200", status, body)
    if status == 200:
        assert_true("results 是列表", isinstance(body.get("results"), list))
        if body["results"]:
            print(f"    → 命中 {body['total']} 条, 耗时 {body['retrieval_time_ms']:.1f}ms")


def test_edge_cases():
    """边界情况"""
    print("\n  [边界测试]")

    # top_k 上下界
    status, body = _req("POST", "/api/retrieval", {"query": "测试", "top_k": 1})
    assert_ok("top_k=1 返回 200", status, body)

    status, body = _req("POST", "/api/retrieval", {"query": "测试", "top_k": 50})
    assert_ok("top_k=50 返回 200", status, body)

    # 空结果
    status, body = _req("POST", "/api/retrieval", {"query": "zzzzz_not_exist_12345", "top_k": 3})
    assert_ok("无匹配查询返回 200", status, body)


def main():
    print("\n── 知识库检索接口测试 ──")

    status, _ = _req("GET", "/health", timeout=5)
    if status != 200:
        print(f"\n  [FAIL] 后端未运行 (GET /health -> {status})")
        sys.exit(1)

    doc_id = ensure_document_indexed()

    test_hybrid()
    test_dense()
    test_sparse()
    test_edge_cases()

    # Cleanup
    if doc_id:
        print("\n  [清理]")
        _req("DELETE", f"/api/documents/{doc_id}")
        print("  已删除测试文档")

    print(f"\n  {PASSED} passed, {FAILED} failed\n")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
