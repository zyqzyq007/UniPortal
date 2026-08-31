#!/usr/bin/env python3
"""
健康检查接口测试

用法:
  python tests/api/test_health.py
"""

import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8000"

PASSED = 0
FAILED = 0


def _req(method, path, timeout=10):
    url = f"{BASE}{path}"
    req = urllib.request.Request(url, method=method)
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
    print("\n── 健康检查接口测试 ──\n")

    # 1. Basic health
    status, body = _req("GET", "/health")
    assert_ok("GET /health 返回 200", status, body)
    assert_true("status == healthy", body.get("status") == "healthy", body)
    assert_true("circuits 字段存在", "circuits" in body, str(body))

    # 2. Detailed health
    status, body = _req("GET", "/api/admin/health")
    assert_ok("GET /api/admin/health 返回 200", status, body)
    services = body.get("services", {})
    for svc in ["llm", "retriever", "milvus"]:
        assert_true(f"services.{svc} 存在", svc in services, f"got: {list(services.keys())}")

    # 3. Root info
    status, body = _req("GET", "/api")
    assert_ok("GET /api 返回 200", status, body)
    assert_true("name 字段存在", "name" in body, str(body))

    # 4. Config
    status, body = _req("GET", "/api/admin/config")
    assert_ok("GET /api/admin/config 返回 200", status, body)
    assert_true("milvus 配置存在", "milvus" in body, str(body))
    assert_true("session 配置存在", "session" in body, str(body))

    print(f"\n  {PASSED} passed, {FAILED} failed\n")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
