#!/usr/bin/env python3
"""
文档管理接口测试

用法:
  python tests/api/test_documents.py
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

TEST_DOC = """# Docker 部署排查指南

## 容器 - 基础概念

### 常见问题：容器无法启动

#### 排故步骤：
1. 检查镜像是否存在且标签正确
2. 检查端口映射是否冲突
3. 检查环境变量与挂载卷配置

#### 常见标识：
- DOCKER-START-FAIL-A：端口占用导致启动失败
- DOCKER-START-FAIL-B：镜像拉取失败
"""


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


def main():
    print("\n── 文档管理接口测试 ──")

    doc_id = None

    # 1. Upload
    print("\n  [上传]")
    status, body = _upload("test_doc.md", TEST_DOC)
    assert_ok("上传文档成功", status, body, expected_status=200)
    if status == 200:
        doc_id = body.get("id")
        assert_true("返回 doc_id", doc_id is not None, str(body))

    # 2. Duplicate upload
    print("\n  [重复上传检测]")
    status, body = _upload("test_doc.md", TEST_DOC)
    assert_ok("重复上传被拒绝 (409)", status, body, expected_status=409)

    # 3. Wait for processing (Q6: poll instead of fixed sleep)
    if doc_id:
        print("\n  [等待处理]")
        print("    等待文档索引完成...")
        _wait_for_indexed(doc_id)

        status, body = _req("GET", f"/api/documents/{doc_id}")
        assert_ok("查询文档状态", status, body)

    # 4. List
    print("\n  [文档列表]")
    status, body = _req("GET", "/api/documents")
    assert_ok("GET /api/documents 返回 200", status, body)
    assert_true("total >= 1", body.get("total", 0) >= 1, f"got: {body.get('total')}")

    # 5. Delete
    if doc_id:
        print("\n  [删除]")
        status, body = _req("DELETE", f"/api/documents/{doc_id}")
        assert_ok("DELETE 返回 200", status, body)

        status, body = _req("GET", f"/api/documents/{doc_id}")
        assert_ok("删除后查询返回 404", status, body, expected_status=404)

    print(f"\n  {PASSED} passed, {FAILED} failed\n")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
