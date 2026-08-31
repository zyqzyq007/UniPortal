"""
MCP Client

Connects to MCP servers (in-process for now) and provides:
- Tool lookup across servers
- Tool execution via call_tool()
- LangChain tool collection for LLM binding
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool

from agent.mcp.server import InProcessMCPServer, MCPServer
from utils.log_utils import log

__all__ = ["MCPClient"]


class MCPClient:
    """
    MCP Client for connecting to in-process MCP servers.

    Aggregates tools from multiple servers and provides:
    - Unified tool lookup by name
    - Tool execution delegating to the owning server
    - LangChain tool collection for LLM binding

    Example:
        >>> client = MCPClient()
        >>> client.add_server(retrieval_server)
        >>> lc_tools = client.get_all_tools_as_langchain()
        >>> bound_llm = llm.bind_tools(lc_tools)
    """

    def __init__(self):
        self._servers: dict[str, InProcessMCPServer] = {}
        # Reverse index: tool_name -> server_name
        self._tool_to_server: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Server management
    # ------------------------------------------------------------------

    def add_server(self, server: InProcessMCPServer) -> None:
        """
        Register an MCP server with this client.

        Args:
            server: The server to add
        """
        server_name = server.config.name
        self._servers[server_name] = server

        # Build reverse index for tool lookup
        for tool_info in server.list_tools():
            tool_name = tool_info["name"]
            if tool_name in self._tool_to_server:
                existing = self._tool_to_server[tool_name]
                log.warning(
                    f"Tool '{tool_name}' already registered by server '{existing}', "
                    f"overwriting with server '{server_name}'"
                )
            self._tool_to_server[tool_name] = server_name

        log.info(f"MCPClient: added server '{server_name}' ({len(server.list_tools())} tools)")

    def remove_server(self, server_name: str) -> None:
        """Remove a server and its tools from the client."""
        if server_name in self._servers:
            server = self._servers[server_name]
            # Remove reverse index entries
            for tool_info in server.list_tools():
                self._tool_to_server.pop(tool_info["name"], None)
            del self._servers[server_name]
            log.info(f"MCPClient: removed server '{server_name}'")

    def get_server(self, server_name: str) -> InProcessMCPServer | None:
        """Get a registered server by name."""
        return self._servers.get(server_name)

    def list_servers(self) -> list[str]:
        """List all registered server names."""
        return list(self._servers.keys())

    # ------------------------------------------------------------------
    # Tool lookup and execution
    # ------------------------------------------------------------------

    def get_tool(self, name: str) -> dict[str, Any] | None:
        """
        Look up a tool by name across all servers.

        Returns:
            Tool info dict with name, description, inputSchema,
            or None if not found.
        """
        server_name = self._tool_to_server.get(name)
        if server_name is None:
            return None

        server = self._servers.get(server_name)
        if server is None:
            return None

        for tool_info in server.list_tools():
            if tool_info["name"] == name:
                return tool_info

        return None

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """
        Execute a tool by name.

        Automatically finds the owning server and delegates.

        Args:
            tool_name: Name of the tool to execute
            arguments: Arguments to pass to the tool

        Returns:
            Tool result

        Raises:
            KeyError: If tool is not found
        """
        server_name = self._tool_to_server.get(tool_name)
        if server_name is None:
            raise KeyError(f"Tool '{tool_name}' not found in any MCP server")

        server = self._servers.get(server_name)
        if server is None:
            raise KeyError(f"Server '{server_name}' not found")

        result = await server.call_tool(tool_name, arguments)

        if not result.success:
            raise RuntimeError(f"Tool '{tool_name}' failed: {result.error}")

        return result.result

    async def call_tool_on_server(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """
        Execute a tool on a specific server.

        Args:
            server_name: Name of the target server
            tool_name: Name of the tool to execute
            arguments: Arguments to pass to the tool

        Returns:
            Tool result
        """
        server = self._servers.get(server_name)
        if server is None:
            raise KeyError(f"Server '{server_name}' not found")

        result = await server.call_tool(tool_name, arguments)

        if not result.success:
            raise RuntimeError(
                f"Tool '{tool_name}' on server '{server_name}' failed: {result.error}"
            )

        return result.result

    # ------------------------------------------------------------------
    # LangChain integration
    # ------------------------------------------------------------------

    def get_all_tools_as_langchain(self) -> list[BaseTool]:
        """
        Collect LangChain tools from all registered servers.

        Returns:
            Combined list of LangChain tools from all servers
        """
        all_tools: list[BaseTool] = []
        for server in self._servers.values():
            if isinstance(server, MCPServer):
                all_tools.extend(server.get_tools_as_langchain())
        return all_tools

    def get_server_tools_as_langchain(self, server_name: str) -> list[BaseTool]:
        """
        Get LangChain tools from a specific server.

        Args:
            server_name: Name of the server

        Returns:
            List of LangChain tools from that server
        """
        server = self._servers.get(server_name)
        if server is None:
            return []
        if isinstance(server, MCPServer):
            return server.get_tools_as_langchain()
        return []

    def list_all_tools(self) -> list[dict[str, Any]]:
        """List all tools from all servers."""
        all_tools: list[dict[str, Any]] = []
        for server in self._servers.values():
            all_tools.extend(server.list_tools())
        return all_tools
