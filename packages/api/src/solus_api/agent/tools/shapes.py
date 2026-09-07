"""The agent-tool envelope shapes (SOLUS-W0-04) — the four core shapes plus
`ArtifactRef`, all Pydantic v2 value objects.

This is what SOL sees: a `ToolCall` goes in, a `ToolResult` comes back, and SOL
branches only on `ToolResult.ok`. Failures are structured `ToolError` DATA, never
exceptions. Large/binary outputs are referenced via `ArtifactRef`, never inlined.
"""

import enum
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from solus_api.models import ArtifactStorage


class ToolErrorCode(enum.StrEnum):
    """What kind of failure a tool call hit. Orthogonal to `ToolError.retryable`,
    which says whether SOL should retry."""

    INVALID_ARGS = "invalid_args"
    NOT_FOUND = "not_found"
    TOOL_ERROR = "tool_error"
    TIMEOUT = "timeout"
    UNAUTHORIZED = "unauthorized"
    # SOLUSDEV-154 (BRG-03): the tool's backing channel has no live session —
    # "bridge offline". Wire-compatible StrEnum addition, pre-sanctioned by the
    # bridge contract §3; flagged as a contract change in the paste file for
    # docs/contracts/agent-tool.md (ratification = humans).
    UNAVAILABLE = "unavailable"


class ToolDescriptor(BaseModel):
    """What a tool advertises to SOL. `description` and `params` are part of the
    interface — the MODEL reads them to decide when and how to call the tool, so they
    are not comments."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str  # unique, stable id (e.g. "get_entity")
    description: str  # natural language, read by the model
    params: dict[str, Any]  # JSON Schema for the arguments
    returns: dict[str, Any]  # JSON Schema for the result `value`
    timeout_seconds: float | None = None  # per-tool override of the registry default
    # Destructive/irreversible (flash, deploy, mutate an external system, delete graph
    # data) → the orchestrator MUST get explicit user confirmation, with the concrete
    # action shown, BEFORE it dispatches the call (CLAUDE.md §7). A declarative marker so
    # the gate is enforced centrally, not hand-rolled per tool; the registry stays a pure
    # dispatcher and does not read it.
    requires_confirmation: bool = False
    #: Solus-authored text for the CONSENT surface, when `description` cannot be
    #: trusted for it. A bridge/MCP tool's `description` is advertised by an
    #: upstream fork — fine as model context (it is length-capped and the model
    #: treats it as data), but it must not phrase the sentence a human reads
    #: before approving a destructive action. Bridge tools set this from their
    #: allowlist `reason`, which Solus writes and review sees.
    consent_summary: str | None = None
    #: Per-tool override of the prompt layer's result cap, for a tool whose whole
    #: point is a payload bigger than the default. A Feature Studio read back at
    #: 4 000 characters is not a Feature Studio — SOL cannot reason about source
    #: it has only seen a truncated prefix of, let alone rewrite it. `None` means
    #: the shared `TOOL_RESULT_CAP`, which stays the default for everything else:
    #: an unbounded result is both an injection surface and a token bill.
    result_cap: int | None = None
    #: Whether `description` is Solus-authored. False for a bridge/MCP tool,
    #: whose description is advertised by an UPSTREAM FORK. Such a description
    #: still has to reach the model — it is how the model picks the right tool —
    #: but prompt assembly fences it so it cannot pose as a Solus instruction.
    #: Deliberately NOT inferred from `consent_summary is not None`: the two
    #: meanings will diverge.
    description_trusted: bool = True
    #: SOLUSDEV-251: a vendor-documentation note about the UI control this tool
    #: acts on (tool knowledge, ADR-033). Rendered by prompt assembly as its OWN
    #: fenced data block, outside the description's fence — never prose.
    knowledge_note: str | None = None


class ToolCall(BaseModel):
    """One invocation SOL proposes. `call_id` correlates the call with its result and
    its logs; it defaults to a fresh id, but a caller may pass its own for tracing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    call_id: str = Field(default_factory=lambda: uuid4().hex)


class ToolError(BaseModel):
    """A structured failure SOL can reason about — never a traceback."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ToolErrorCode
    message: str
    retryable: bool = False  # transient (retry may help) vs permanent


class ToolResult(BaseModel):
    """The single envelope every tool call returns. SOL branches on `ok`: on success
    it consumes `value`, on failure it reads `error`. The ok/value/error invariant is
    enforced so a malformed result can never reach the model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: str  # echoes the ToolCall id
    ok: bool
    value: dict[str, Any] | None = None  # JSON-serializable; large data via ArtifactRef
    error: ToolError | None = None

    @model_validator(mode="after")
    def _check_invariant(self) -> Self:
        if self.ok and (self.value is None or self.error is not None):
            raise ValueError("an ok result must carry a value and no error")
        if not self.ok and (self.error is None or self.value is not None):
            raise ValueError("a failed result must carry an error and no value")
        return self

    @classmethod
    def success(cls, call_id: str, value: dict[str, Any]) -> Self:
        return cls(call_id=call_id, ok=True, value=value)

    @classmethod
    def failure(cls, call_id: str, error: ToolError) -> Self:
        return cls(call_id=call_id, ok=False, error=error)


class ArtifactRef(BaseModel):
    """A reference to large/binary bytes that are NEVER inlined into a result. SOL
    reasons over `summary`; the bytes are fetched lazily only when a step genuinely
    needs them (e.g. a vision-model call). Backed by the `artifacts` table."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: UUID  # handle into the `artifacts` table
    uri: str  # where the bytes live
    media_type: str  # e.g. image/png, application/octet-stream
    storage: ArtifactStorage  # S3 | LOCAL | CLIENT
    size_bytes: int | None = None  # so a consumer knows the cost before fetching
    summary: str | None = None  # text the model reasons over WITHOUT fetching the bytes
