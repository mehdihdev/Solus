"""Agent-tool interface (SOLUS-W0-04): how SOL invokes capabilities uniformly and
safely, without the reasoning code knowing how each is implemented.

FUNCTIONAL end to end: the shapes, the `Tool` protocol + `InProcessTool`, the
`ToolRegistry` (whose `invoke` never raises), and the reference `get_entity` tool.
Future tool kinds (MCP/Desktop/Environment) and the artifact byte-fetch flow are
documented in docs/contracts/agent-tool.md, not built here.
"""

from solus_api.agent.tools.get_entity import GET_ENTITY_DESCRIPTOR, build_get_entity_tool
from solus_api.agent.tools.registry import DEFAULT_TIMEOUT_SECONDS, ToolRegistry
from solus_api.agent.tools.shapes import (
    ArtifactRef,
    ToolCall,
    ToolDescriptor,
    ToolError,
    ToolErrorCode,
    ToolResult,
)
from solus_api.agent.tools.tool import InProcessTool, Tool, ToolException, ToolHandler

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "GET_ENTITY_DESCRIPTOR",
    "ArtifactRef",
    "InProcessTool",
    "Tool",
    "ToolCall",
    "ToolDescriptor",
    "ToolError",
    "ToolErrorCode",
    "ToolException",
    "ToolHandler",
    "ToolRegistry",
    "ToolResult",
    "build_get_entity_tool",
]
