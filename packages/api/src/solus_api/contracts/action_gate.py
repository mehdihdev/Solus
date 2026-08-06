"""SOLUSDEV-218 (CTR-03) — the destructive-action gate contract.

THIS DOCUMENTS A SHIPPED GATE. IT DOES NOT REDESIGN ONE. Every shape is read
from the SOLUS-ONS-A5 implementation on branch
`SOLUSDEV-60/ons-ui01-confirmation-surface` (commit 8c9b812):

===========================  ===============================================
`ConfirmationStatus`         `solus_api/models.py:176-190`
`ToolConfirmation` columns   `solus_api/models.py:654-699`
the decision body            `solus_api/schemas.py:166-175`
the decide endpoint          `solus_api/routers/sol.py:446-494`
park / decide / STALE        `solus_api/agent/confirmations.py`
the streamed event           `solus_api/agent/stream.py:57-81`
===========================  ===============================================

.. warning::
   That work is **not yet on** ``main``. On ``main`` today the gate is a flat
   fail-closed refusal (``solus_api/agent/runtime.py:162``): a tool declaring
   ``requires_confirmation`` is structurally un-dispatchable. Publishing the
   shape here is what lets the Tool viewport (WS-06) and the Impact widget
   (IMP-03) build the approval surface while the SOL lane builds the dispatcher.

The models are **read models for a UI**, deliberately separate from the
authoritative server models. `ToolConfirmation` (the ORM row) stays where it is;
this is the wire shape a client sees, and it is the TypeScript twin's mirror —
see `packages/shared-types/src/action-gate.ts` and `docs/contracts/action-gate.md`.
"""

from __future__ import annotations

import enum
from typing import Any, Final, Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from solus_api.agent.tools.shapes import ToolError, ToolResult

#: How long a parked action stays approvable — mirrors
#: `solus_api.agent.confirmations.CONFIRMATION_TTL`. Short on purpose: an
#: approval is consent to a specific edit against a specific model state.
CONFIRMATION_TTL_MINUTES: Final = 30

#: The shipped decide route (`routers/sol.py:446`).
CONFIRMATION_DECISION_ROUTE: Final = (
    "/api/v1/projects/{project_id}/sol/confirmations/{confirmation_id}"
)


class ConfirmationStatus(enum.StrEnum):
    """Lifecycle of one approval. Mirrors `solus_api.models.ConfirmationStatus`.

    Terminal in every state but PENDING — an approval is SINGLE USE, so a
    decided row can never be replayed into a second execution.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    #: Approved, but what the action would DO had changed since the user was
    #: shown it — so nothing ran. Distinct from EXPIRED: time did not run out,
    #: the world moved. A user who approved one thing did not consent to another.
    STALE = "stale"


class DiffRow(BaseModel):
    """One row of the diff being approved.

    Generic across every tool kind by construction — a CAD edit, a firmware
    flash and a robot command all render the same three fields. `before` is
    None for an action that does not REPLACE a value; the row then reports the
    argument the action will run with, read from the same stored dict that
    executes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(max_length=200)
    before: str | None = Field(default=None, max_length=500)
    after: str | None = Field(default=None, max_length=500)


class ToolConfirmationEvent(BaseModel):
    """The `tool_confirmation` SSE payload: an action parked for approval.

    Carries the CONCRETE action — tool, arguments, a readable summary and the
    diff — because a user cannot meaningfully approve an opaque id.

    `summary` is authored by Solus. For a bridge tool the upstream fork's own
    `description` is untrusted text and must never phrase the sentence a human
    reads before approving something destructive; the gate prefers the
    Solus-written `consent_summary` when one exists (`confirmations.py:76-95`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    confirmation_id: str
    tool: str = Field(max_length=128)
    #: The STORED arguments — displayed is executed. A client cannot change them.
    args: dict[str, Any] = Field(default_factory=dict)
    summary: str = Field(max_length=2048)
    #: Empty when the tool offers no preview; the summary is then the consent.
    preview: list[DiffRow] = Field(default_factory=list, max_length=50)


class ConfirmationDecisionRequest(BaseModel):
    """The decide request body: a decision and NOTHING ELSE.

    `extra="forbid"` is the whole security property of the round-trip. A body
    carrying its own `args` is a 422 rather than a merge — otherwise a user
    could approve "change width" and a client execute "change everything"
    (`schemas.py:166-175`).

    **There is no `amend`.** Amend means client-supplied arguments at decision
    time, which is precisely what this forbids. To change an action, reject it
    and ask SOL to propose the new one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Literal["approve", "reject"]


class ConfirmationOutcomeEnvelope(BaseModel):
    """The decide endpoint's 200 body: the standard envelope around a `ToolResult`.

    .. warning::
       **HTTP 200 does not mean the action ran.** Wrong project, already
       decided, expired, rejected, stale and tool-gone are ALL 200 with
       ``data.ok is False``. Only a non-member gets a 4xx — a 404, deliberately,
       so there is no existence oracle. A UI that treats 200 as success is wrong.

    `ToolResult` is reused rather than re-declared: the W0-04 never-raises
    contract holds through this path, and a second copy of the envelope would be
    one more thing to drift.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    data: ToolResult


def confirmation_decision_path(project_id: str, confirmation_id: str) -> str:
    """The shipped decide route with its segments escaped."""
    return CONFIRMATION_DECISION_ROUTE.format(
        project_id=quote(project_id, safe=""),
        confirmation_id=quote(confirmation_id, safe=""),
    )


__all__ = [
    "CONFIRMATION_DECISION_ROUTE",
    "CONFIRMATION_TTL_MINUTES",
    "ConfirmationDecisionRequest",
    "ConfirmationOutcomeEnvelope",
    "ConfirmationStatus",
    "DiffRow",
    "ToolConfirmationEvent",
    "ToolError",
    "ToolResult",
    "confirmation_decision_path",
]
