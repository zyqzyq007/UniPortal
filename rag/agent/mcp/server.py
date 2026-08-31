"""
MCP Server for Agent Architecture

Provides the Model Context Protocol server with:
- Base MCPServer: tool registry and execution
- MCPServer: Extended server with LangChain tool conversion
- InProcessMCPServer: In-process server for direct tool registration

Protocol: https://modelcontextprotocol.io
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import create_model

from utils.log_utils import log

__all__ = [
    "MCPServerConfig",
    "MCPTool",
    "MCPToolResult",
    "MCPServer",
    "InProcessMCPServer",
]


# =============================================================================
# Core data types
# =============================================================================


@dataclass
class MCPServerConfig:
    """Configuration for MCP server."""

    name: str = "rag-mcp-server"
    version: str = "1.0.0"
    description: str = "MCP Server for Enterprise RAG Platform"


@dataclass
class MCPTool:
    """MCP tool definition."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable


@dataclass
class MCPToolResult:
    """Result from tool execution."""

    success: bool
    result: Any
    error: str | None = None


# =============================================================================
# Base MCP Server
# =============================================================================


class _BaseMCPServer:
    """
    MCP Server base implementation.

    Provides a registry for tools and handles tool execution.
    """

    def __init__(self, config: MCPServerConfig | None = None):
        self.config = config or MCPServerConfig()
        self._tools: dict[str, MCPTool] = {}
        log.info(f"MCPServer initialized: {self.config.name}")

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable,
    ):
        if name in self._tools:
            log.warning(f"Tool '{name}' already registered, overwriting")
        self._tools[name] = MCPTool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
        )
        log.debug(f"Tool registered: {name}")

    def unregister_tool(self, name: str):
        if name in self._tools:
            del self._tools[name]
            log.debug(f"Tool unregistered: {name}")

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        if name not in self._tools:
            return MCPToolResult(
                success=False,
                result=None,
                error=f"Tool '{name}' not found",
            )

        tool = self._tools[name]

        try:
            argument_keys = sorted(str(key) for key in arguments)
            log.info(f"Executing tool: {name}, argument_keys={argument_keys}")
            import asyncio

            if asyncio.iscoroutinefunction(tool.handler):
                result = await tool.handler(**arguments)
            else:
                result = tool.handler(**arguments)
            return MCPToolResult(success=True, result=result)
        except Exception as exc:
            error_type = type(exc).__name__
            log.error(f"Tool execution failed: tool={name}, error_type={error_type}")
            return MCPToolResult(
                success=False,
                result=None,
                error=f"{error_type}: tool execution failed",
            )

    def get_tool_schemas_for_llm(self) -> list[dict[str, Any]]:
        schemas = []
        for tool in self._tools.values():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
            )
        return schemas

    def bind_to_llm(self, llm):
        schemas = self.get_tool_schemas_for_llm()
        return llm.bind_tools(schemas)


# =============================================================================
# Extended MCPServer with LangChain integration
# =============================================================================


class MCPServer(_BaseMCPServer):
    """
    MCP Server with LangChain tool conversion.

    Adds methods to convert registered MCP tools into LangChain
    StructuredTool instances so they can be bound to an LLM via
    llm.bind_tools().
    """

    def get_tools_as_langchain(self) -> list[StructuredTool]:
        """Convert all registered MCP tools to LangChain StructuredTool instances."""
        lc_tools: list[StructuredTool] = []
        for tool in self._tools.values():
            lc_tools.append(self._mcp_to_langchain(tool))
        return lc_tools

    @staticmethod
    def _mcp_to_langchain(tool: MCPTool) -> StructuredTool:
        """Convert a single MCPTool to a LangChain StructuredTool."""
        input_schema = tool.input_schema or {}
        properties = input_schema.get("properties", {})
        required_fields = set(input_schema.get("required", []))

        field_definitions: dict[str, Any] = {}
        for prop_name, prop_def in properties.items():
            prop_type = str
            if isinstance(prop_def, dict):
                ptype = prop_def.get("type", "string")
                if ptype == "integer":
                    prop_type = int
                elif ptype == "number":
                    prop_type = float
                elif ptype == "boolean":
                    prop_type = bool
                elif ptype == "array":
                    prop_type = list
                elif ptype == "object":
                    prop_type = dict

            if prop_name in required_fields:
                field_definitions[prop_name] = (prop_type, ...)
            else:
                default = prop_def.get("default") if isinstance(prop_def, dict) else None
                if default is not None:
                    field_definitions[prop_name] = (prop_type, default)
                else:
                    field_definitions[prop_name] = (prop_type | None, None)

        model_name = f"{tool.name}_Input"
        try:
            InputModel = create_model(model_name, **field_definitions)
        except Exception:
            InputModel = create_model(model_name, query=(str, ...))

        handler = tool.handler

        def _make_sync_func(h):
            def func(**kwargs):
                import asyncio

                if asyncio.iscoroutinefunction(h):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None
                    if loop and loop.is_running():
                        import concurrent.futures

                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                            future = pool.submit(asyncio.run, h(**kwargs))
                            return future.result()
                    else:
                        return asyncio.run(h(**kwargs))
                return h(**kwargs)

            return func

        sync_func = _make_sync_func(handler)

        async def coro_func(**kwargs):
            if asyncio.iscoroutinefunction(handler):
                return await handler(**kwargs)
            return handler(**kwargs)

        return StructuredTool.from_function(
            func=sync_func,
            coroutine=coro_func,
            name=tool.name,
            description=tool.description,
            args_schema=InputModel,
        )

    # ------------------------------------------------------------------
    # Convenience: register from a plain callable
    # ------------------------------------------------------------------

    def register_callable(
        self,
        func: Callable,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """
        Register a tool from a plain callable by inspecting its signature.

        Auto-generates input_schema from the function's type annotations.
        """
        name = name or func.__name__
        description = description or inspect.getdoc(func) or f"Tool: {name}"

        sig = inspect.signature(func)
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue

            prop: dict[str, Any] = {"type": "string"}
            annotation = param.annotation

            if annotation != inspect.Parameter.empty:
                if annotation is int:
                    prop["type"] = "integer"
                elif annotation is float:
                    prop["type"] = "number"
                elif annotation is bool:
                    prop["type"] = "boolean"
                elif annotation is list:
                    prop["type"] = "array"

            properties[param_name] = prop

            if param.default is inspect.Parameter.empty:
                required.append(param_name)
            else:
                prop["default"] = param.default

        self.register_tool(
            name=name,
            description=description,
            input_schema={"type": "object", "properties": properties, "required": required},
            handler=func,
        )


# =============================================================================
# In-process MCP Server
# =============================================================================


class InProcessMCPServer(MCPServer):
    """
    MCP Server for in-process use (no networking).

    The agent's MCPClient connects to InProcessMCPServer instances
    directly in memory -- no serialization or transport overhead.
    """

    def __init__(self, config: MCPServerConfig | None = None):
        super().__init__(config)
        self._started = False

    def start(self) -> None:
        self._started = True
        log.info(f"InProcessMCPServer started: {self.config.name}")

    def stop(self) -> None:
        self._started = False
        log.info(f"InProcessMCPServer stopped: {self.config.name}")

    @property
    def is_running(self) -> bool:
        return self._started

    def __enter__(self) -> InProcessMCPServer:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
