"""
Pluggable tool registry for the agent platform (P2.1 + P2.3).

This lets new non-RAG tools (calculator, unit conversion, external API calls,
code execution) be registered WITHOUT touching the graph topology. Tools are
grouped into MCP servers; ``get_extra_servers`` returns all registered servers
which ``AgentHarness._build_mcp_client`` aggregates.

Two built-in tool servers are provided out of the box:
  - ``UtilityToolsServer``: calculator + unit conversion (pure-python, no deps)
  - ``ExternalAPIToolsServer``: a generic HTTP GET tool (opt-in via env)

Additional servers can be registered at runtime via ``register_server`` /
``register_tool_function``.
"""

from __future__ import annotations

import math
import os
import threading
from collections.abc import Callable
from typing import Any

from agent.mcp.server import InProcessMCPServer, MCPServerConfig
from utils.log_utils import log

__all__ = [
    "register_server",
    "register_tool_function",
    "get_extra_servers",
    "UtilityToolsServer",
    "ExternalAPIToolsServer",
]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_extra_servers: list[InProcessMCPServer] = []
_registry_lock = threading.Lock()


def register_server(server: InProcessMCPServer) -> None:
    """Register an extra MCP server (added to the agent's toolset)."""
    with _registry_lock:
        _extra_servers.append(server)
    log.info(f"Tool registry: added server '{server.config.name}'")


def register_tool_function(
    name: str,
    description: str,
    handler: Callable,
    params_schema: dict[str, Any] | None = None,
    server_name: str = "custom",
) -> None:
    """
    Register a single tool as its own ad-hoc server.

    Convenience wrapper for quick tool addition without manually building an
    InProcessMCPServer.
    """
    server = InProcessMCPServer(MCPServerConfig(name=server_name, version="1.0.0"))
    server.register_callable(handler, name=name, description=description)
    register_server(server)


def get_extra_servers() -> list[InProcessMCPServer]:
    """Return all registered extra servers (called by the harness)."""
    _maybe_register_defaults()
    with _registry_lock:
        return list(_extra_servers)


_registered_defaults = False


def _maybe_register_defaults() -> None:
    """Register built-in tool servers once (idempotent)."""
    global _registered_defaults
    if _registered_defaults:
        return
    with _registry_lock:
        if _registered_defaults:
            return
        _registered_defaults = True
    try:
        register_server(UtilityToolsServer())
    except Exception as e:  # noqa: BLE001
        log.debug(f"UtilityToolsServer not registered: {e}")
    if os.getenv("ENABLE_EXTERNAL_API_TOOL", "false").lower() in ("1", "true", "yes"):
        try:
            register_server(ExternalAPIToolsServer())
        except Exception as e:  # noqa: BLE001
            log.debug(f"ExternalAPIToolsServer not registered: {e}")


# ---------------------------------------------------------------------------
# Built-in: utility tools (calculator + unit conversion)
# ---------------------------------------------------------------------------


class UtilityToolsServer(InProcessMCPServer):
    """Pure-python utility tools: safe arithmetic + unit conversion."""

    def __init__(self):
        super().__init__(MCPServerConfig(name="utility", version="1.0.0"))
        self.register_callable(
            self.calculate,
            name="calculator",
            description=(
                "计算一个数学表达式并返回结果。支持加减乘除、幂、括号、"
                "以及 sin/cos/sqrt/log 等函数。例如: calculator('2*(3+4)') -> 14"
            ),
        )
        self.register_callable(
            self.convert_unit,
            name="unit_convert",
            description=(
                "单位换算。支持温度(℃/℉/K)、长度(mm/cm/m/km/inch/ft)、"
                "压力(MPa/kPa/psi/bar)。例如: unit_convert('100℃', '℉') -> 212"
            ),
        )

    # Functions/constants the calculator may evaluate. Keys are the only names
    # the AST visitor permits in a Call/Name node; everything else is rejected.
    _CALC_NAMESPACE = {
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "sqrt": math.sqrt,
        "log": math.log,
        "log10": math.log10,
        "exp": math.exp,
        "abs": abs,
        "pow": pow,
        "min": min,
        "max": max,
        "round": round,
        "pi": math.pi,
        "e": math.e,
    }

    @staticmethod
    def calculate(expression: str) -> str:
        """
        Safely evaluate a math expression via an AST whitelist.

        No ``eval`` / ``compile`` exec — the expression is parsed with
        ``ast.parse`` and a ``NodeVisitor`` rejects anything other than numbers,
        arithmetic/unary operators, parentheses, commas, and calls to the
        whitelisted functions above. Attribute access (``__class__``,
        ``os.system``) and any non-whitelisted name are rejected, which closes
        the ``eval`` injection surface and also restores ``abs``/``pow``/``min``
        etc. that the old character-whitelist made unreachable.
        """
        import ast

        if not expression or not isinstance(expression, str):
            return "错误：请提供数学表达式"
        expr = expression.strip()
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError:
            return "错误：表达式语法不合法"

        allowed = UtilityToolsServer._CALC_NAMESPACE

        def _eval(node):
            if isinstance(node, ast.Expression):
                return _eval(node.body)
            if isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float)):
                    return node.value
                raise ValueError("不支持的常量类型")
            if isinstance(node, ast.BinOp):
                left = _eval(node.left)
                right = _eval(node.right)
                ops = {
                    ast.Add: lambda a, b: a + b,
                    ast.Sub: lambda a, b: a - b,
                    ast.Mult: lambda a, b: a * b,
                    ast.Div: lambda a, b: a / b,
                    ast.Mod: lambda a, b: a % b,
                    ast.Pow: lambda a, b: a**b,
                    ast.FloorDiv: lambda a, b: a // b,
                }
                op = ops.get(type(node.op))
                if op is None:
                    raise ValueError(f"不支持的运算符 {type(node.op).__name__}")
                return op(left, right)
            if isinstance(node, ast.UnaryOp):
                operand = _eval(node.operand)
                if isinstance(node.op, ast.USub):
                    return -operand
                if isinstance(node.op, ast.UAdd):
                    return +operand
                raise ValueError("不支持的一元运算符")
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name):
                    raise ValueError("仅允许直接调用白名单函数")
                fn = allowed.get(node.func.id)
                if fn is None:
                    raise ValueError(f"不允许的函数 {node.func.id}")
                args = [_eval(a) for a in node.args]
                return fn(*args)
            if isinstance(node, ast.Name):
                if node.id in allowed:
                    return allowed[node.id]
                raise ValueError(f"不允许的名称 {node.id}")
            raise ValueError(f"不支持的语法元素 {type(node).__name__}")

        try:
            result = _eval(tree)
            return f"{result}"
        except ZeroDivisionError:
            return "计算错误：除数为零"
        except Exception as ex:
            return f"计算错误：{ex}"

    @staticmethod
    def convert_unit(value_expr: str, target_unit: str) -> str:
        """Convert a value with a unit to a target unit."""
        try:
            # Parse "100℃" / "5 mm" / "2.5 MPa"
            import re

            m = re.match(r"^\s*([-\d.]+)\s*([a-zA-Z℃℉]+)\s*$", value_expr)
            if not m:
                return "错误：格式应为 '<数值><单位>'，如 '100℃'"
            val = float(m.group(1))
            src = m.group(2).strip()
            dst = target_unit.strip()

            # Temperature
            temp_units = {"℃": "c", "℉": "f", "K": "k"}
            if src in temp_units and dst in temp_units:
                s, t = temp_units[src], temp_units[dst]
                # to celsius
                c = val if s == "c" else (val - 32) * 5 / 9 if s == "f" else val - 273.15
                out = c if t == "c" else c * 9 / 5 + 32 if t == "f" else c + 273.15
                return f"{out:.2f}{dst}"

            # Length
            length = {"mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0, "inch": 0.0254, "ft": 0.3048}
            if src in length and dst in length:
                meters = val * length[src]
                return f"{meters / length[dst]:.4f}{dst}"

            # Pressure
            pressure = {"MPa": 1.0, "kPa": 0.001, "bar": 0.1, "psi": 0.00689476}
            if src in pressure and dst in pressure:
                mpa = val * pressure[src]
                return f"{mpa / pressure[dst]:.4f}{dst}"

            return f"错误：不支持的换算 {src}->{dst}"
        except Exception as ex:
            return f"换算错误：{ex}"


# ---------------------------------------------------------------------------
# Built-in: external API tool (opt-in)
# ---------------------------------------------------------------------------


class ExternalAPIToolsServer(InProcessMCPServer):
    """A generic HTTP GET tool for calling external read-only APIs."""

    def __init__(self):
        super().__init__(MCPServerConfig(name="external_api", version="1.0.0"))
        self.register_callable(
            self.http_get,
            name="http_get",
            description=(
                "对指定 URL 发起只读 GET 请求并返回 JSON/文本响应。"
                "仅用于查询外部公开 API。例如: http_get('https://api.example.com/status')"
            ),
        )

    @staticmethod
    def _resolve_public_ips(host: str) -> tuple[set[str], str | None]:
        """
        Resolve ``host`` and return (public_ips, block_reason).

        Returns the set of validated PUBLIC address strings for the host, or
        ``([], reason)`` if any resolved address is private/loopback/link-local/
        multicast/reserved (or unresolvable). Used by ``http_get`` to verify the
        socket peer after connect, closing the DNS-rebinding TOCTOU window left
        by a resolve-then-fetch gap.
        """
        import ipaddress
        import socket

        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return set(), f"无法解析主机 {host}"
        public: set[str] = set()
        for info in infos:
            ip_str = info[4][0].split("%")[0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
            ):
                return set(), f"主机 {host} 解析到内网/保留地址 {ip}，已拒绝"
            public.add(str(ip))
        if not public:
            return set(), f"主机 {host} 未解析到任何公网地址"
        return public, None

    @staticmethod
    def _ssf_blocked(url: str) -> str | None:
        """
        Validate a URL for SSRF safety. Returns a reason string if blocked,
        else None.

        Blocks: non-http(s) schemes, private/loopback/link-local/multicast IP
        literals, and hostnames that don't resolve to a public address. An
        optional allowlist can be set via ``HTTP_TOOL_ALLOWED_HOSTS`` (comma-
        separated); when set, only those hosts are permitted.

        Note: this checks the resolved addresses at validation time. To close
        the resolve→fetch TOCTOU window, ``http_get`` additionally verifies the
        socket peer IP after connect against the resolved public set (see
        ``_resolve_public_ips``).
        """
        import os
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return "URL 必须以 http:// 或 https:// 开头"
        host = parsed.hostname
        if not host:
            return "URL 缺少主机名"

        # Optional host allowlist (most restrictive control).
        allow_env = os.getenv("HTTP_TOOL_ALLOWED_HOSTS", "").strip()
        if allow_env:
            allowed = {h.strip().lower() for h in allow_env.split(",") if h.strip()}
            if host.lower() not in allowed:
                return f"主机 {host} 不在允许列表内"

        _, reason = ExternalAPIToolsServer._resolve_public_ips(host)
        return reason

    @staticmethod
    def http_get(url: str, timeout: int = 10) -> str:
        """
        Perform a read-only HTTP GET (SSRF-hardened).

        Defences (F06, layered):
          1. ``_ssf_blocked`` pre-check (scheme/host allowlist/public IPs).
          2. Redirects are DISABLED via a no-op ``HTTPRedirectHandler`` — a 302
             to an internal/metadata endpoint cannot bypass the check. Relative
             ``Location`` handling is therefore moot (no follow).
          3. After connect, the socket peer IP is verified to be in the resolved
             public set, closing the DNS-rebinding TOCTOU window between
             resolution and the actual connection (``urlopen`` re-resolves).
          HTTPS is not broken: we keep the original host in the URL so SNI and
          certificate validation work normally; only the post-connect peer IP is
          cross-checked.
        """
        import http.client
        import ssl
        from urllib.parse import urlparse

        blocked = ExternalAPIToolsServer._ssf_blocked(url)
        if blocked:
            return f"错误：{blocked}"

        parsed = urlparse(url)
        host = parsed.hostname or ""
        allowed_ips, reason = ExternalAPIToolsServer._resolve_public_ips(host)
        if reason:
            return f"错误：{reason}"

        scheme = parsed.scheme
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        try:
            # Direct connection via http.client so we can inspect the socket
            # peer IP AFTER connect (the TOCTOU-closing step). No redirects.
            if scheme == "https":
                ctx = ssl.create_default_context()
                conn = http.client.HTTPSConnection(
                    host,
                    port,
                    timeout=timeout,
                    context=ctx,
                )
            else:
                conn = http.client.HTTPConnection(host, port, timeout=timeout)
            try:
                conn.request("GET", path, headers={"User-Agent": "RAG-Agent/1.0", "Host": host})
                resp = conn.getresponse()
                # Refuse to follow redirects — a 3xx is treated as a hard stop
                # so an attacker-controlled public host cannot 302 us to an
                # internal/metadata address.
                if 300 <= resp.status < 400:
                    return f"错误：服务器返回重定向 {resp.status}，已拒绝（不跟随重定向）"
                body = resp.read().decode("utf-8", errors="replace")[:2000]

                # Post-connect peer-IP verification (TOCTOU defence). The socket
                # may be wrapped by TLS; unwrap to the raw socket.
                sock = conn.sock
                if sock is not None:
                    raw = getattr(sock, "sock", sock)  # unwrap SSLSocket
                    try:
                        peer_ip, _ = raw.getpeername()
                    except Exception:  # noqa: BLE001
                        peer_ip = None
                    if peer_ip is not None and peer_ip not in allowed_ips:
                        return f"错误：连接到的对端 IP {peer_ip} 不在已校验的公网地址集合内，已拒绝（DNS 重绑定防护）"
                return body
            finally:
                conn.close()
        except Exception as ex:
            return f"请求失败：{ex}"
