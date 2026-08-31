"""
Agent MCP Package

Provides MCP (Model Context Protocol) integration for the agent system:
- MCPServer: Extended MCP server with LangChain tool conversion
- InProcessMCPServer: In-process server for direct tool registration
- MCPRetrievalServer: Pre-configured server exposing RAG retrieval tools
- MCPClient: Client for connecting to MCP servers and aggregating tools
- retriever_tools: RetrieverManager, MilvusRetriever, get_retriever_tool
"""

from agent.mcp.client import MCPClient
from agent.mcp.retrieval_server import MCPRetrievalServer
from agent.mcp.server import InProcessMCPServer, MCPServer

__all__ = [
    "MCPServer",
    "InProcessMCPServer",
    "MCPRetrievalServer",
    "MCPClient",
]
