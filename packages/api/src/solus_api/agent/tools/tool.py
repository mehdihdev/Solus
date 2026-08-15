"""The `Tool` protocol and its v1 implementation (SOLUS-W0-04).

`Tool` is a Protocol, not a bare function, so different KINDS of capability plug in
behind ONE interface — SOL and the registry never change when a new kind is added.
v1 ships `InProcessTool` (an async Python callable). Future kinds — RemoteTool/MCPTool
(an external MCP server), DesktopTool (UI / "being the cursor"), EnvironmentTool
(operate a device) — are further implementations of this same protocol; see
docs/contracts/agent-tool.md.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class Tool(Protocol):
    """Every capability SOL can invoke, seen uniformly."""

    @property
    def descriptor(self) -> ToolDescriptor: ...

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        """Run the capability and return its JSON-serializable `value`. Raise
        `ToolException` to signal a typed failure (e.g. NOT_FOUND). A tool NEVER
        returns a `ToolResult` and NEVER handles its own timeout — the registry wraps
        every call into a structured result."""
        ...


class ToolException(Exception):  # noqa: N818 — name fixed by the W0-04 contract ("raises ToolException")
    """A tool's typed failure signal. The registry turns it into a `ToolResult` with
    this `code`/`message`/`retryable`. The message is author-written, so it is safe to
    show the model — unlike an unexpected exception, whose text is never surfaced."""

    def __init__(
        self,
        message: str,
        *,
        code: ToolErrorCode = ToolErrorCode.TOOL_ERROR,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


#: What a confirmation-gated tool answers when asked "what exactly will change?"
#: — the rows the user approves. Generic across tool kinds: a CAD edit, a
#: firmware flash and a robot command all render the same `{label, before,
#: after}` shape (SOLUS-ONS-A5).
ToolPreview = Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]]


class InProcessTool:
    """v1 Tool kind: wraps an async Python callable. The descriptor is fixed at
    construction; `invoke` just runs the handler — arg validation and failure handling
    live in the registry, so the handler stays a plain async function.

    `preview` is optional and NOT part of the `Tool` protocol: the confirmation
    flow duck-types it, exactly like a connector's `list_selectable`. A gated
    tool that can describe its change supplies one; one that cannot simply does
    not, and its summary carries the consent."""

    def __init__(
        self,
        descriptor: ToolDescriptor,
        handler: ToolHandler,
        preview: ToolPreview | None = None,
    ) -> None:
        self._descriptor = descriptor
        self._handler = handler
        if preview is not None:
            self.preview = preview

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        return await self._handler(args)
