"""SOLUS-TU-04 — the /api/v1/toolkb HTTP surface, with the TU-06 guard in front.

Route plan: docs/api/toolkb.md (tier-1 amendment, this ticket).

Structural properties (Phase-4 review hardened):

- **HTTP submissions are pinned to the operator tier.** ``acquired_via`` /
  ``endpoint_scope`` are properties of Solus-side ingestion code, not of a
  request body — a client claiming "api_geometry, global scope" would skip the
  vendor-control allowlist and forge the 0.9 confidence stamp the human
  reviewer trusts. Server-side jobs (docs ingestion, future
  bridge-authenticated probes) call ``guard.ingest`` directly with a context
  they can vouch for.
- **The body is taken as ``Any`` and shape-checked here, sanitized.** The
  framework's own 422 handler echoes offending input back (``exc.errors()``
  includes it); nothing from a rejected toolkb body may ever echo.
- The GET is deliberately team-unscoped — the store is cross-tenant by
  design; the boundary is what rows cannot contain. Rows that fail CTR-05
  re-validation at read time are omitted and named in logs by id/tool only.
"""

import logging
import uuid
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, ConfigDict, ValidationError

from solus_api.contracts.tool_knowledge import ControlEffect, ToolFamily, UiSurface
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, RequireVerified, SessionDep
from solus_api.services.events import emit_event
from solus_api.toolkb.feedback import Verdict, apply_feedback
from solus_api.toolkb.guard import IngestContext, IngestRejectedError, ingest
from solus_api.toolkb.guides import list_guides, resolve_guide
from solus_api.toolkb.schema import AcquisitionMethod, ToolKnowledgeEntry, to_contract
from solus_api.toolkb.storage import MAX_QUERY_LIMIT, query_entries

logger = logging.getLogger("solus.toolkb")

router = APIRouter(prefix="/api/v1/toolkb", tags=["toolkb"])


def _entry_of(payload: Any) -> Mapping[str, Any]:
    """Sanitized body shape-check — error messages are fixed strings; nothing
    from the body (values OR keys, which are attacker-chosen too) is echoed."""
    if not isinstance(payload, Mapping):
        raise APIError(422, "contract_validation", "body must be a JSON object")
    if set(payload) != {"entry"}:
        raise APIError(422, "contract_validation", "body must contain exactly one field: 'entry'")
    entry = payload["entry"]
    if not isinstance(entry, Mapping):
        raise APIError(422, "contract_validation", "'entry' must be a JSON object")
    return entry


def _serialize_entry(row: ToolKnowledgeEntry) -> dict[str, Any]:
    data = to_contract(row).model_dump(mode="json")
    data["id"] = str(row.id)
    data["confidence"] = row.confidence
    data["last_verified_at"] = (
        row.last_verified_at.isoformat() if row.last_verified_at is not None else None
    )
    return data


@router.post("/entries", status_code=201)
async def submit_entry(
    payload: Annotated[Any, Body()],
    user: CurrentUser,
    _verified: RequireVerified,
    session: SessionDep,
) -> dict[str, Any]:
    entry = _entry_of(payload)
    # Pinned server-side: the lowest trust tier. Never derived from the body.
    ctx = IngestContext(acquired_via=AcquisitionMethod.OPERATOR)
    try:
        row = await ingest(session, entry=entry, ctx=ctx)
    except IngestRejectedError as exc:
        # The event names the tool and reason only — rejected content is
        # suspect by definition and stays out of the event store too. The tool
        # value is re-parsed against the enum: raw claim, raw junk possible.
        try:
            tool_value = ToolFamily(str(entry.get("tool", ""))).value
        except ValueError:
            tool_value = "unknown"
        emit_event(
            session,
            user=user,
            event_type="tool_knowledge.rejected",
            payload={"tool": tool_value, "reason": exc.reason.value},
        )
        await session.commit()
        # exc.detail carries field names and rule text, never the input.
        raise APIError(
            422, exc.reason.value, f"Rejected by the tenancy guard: {exc.detail}"
        ) from exc
    emit_event(
        session,
        user=user,
        event_type="tool_knowledge.submitted",
        payload={
            "tool": row.tool.value,
            "control_id": row.control_id,
            "status": row.status.value,
            "acquired_via": row.acquired_via.value,
        },
    )
    await session.commit()
    return envelope({"id": str(row.id), "status": row.status.value, "confidence": row.confidence})


class FeedbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict


@router.post("/entries/{entry_id}/feedback")
async def submit_feedback(
    entry_id: uuid.UUID,
    body: FeedbackBody,
    user: CurrentUser,
    _verified: RequireVerified,
    session: SessionDep,
) -> dict[str, Any]:
    """TU-08: a user confirms or rejects a guidance step. Recomputes confidence
    deterministically (a reject pulls down hard — precision over recall)."""
    try:
        entry = await apply_feedback(session, entry_id=entry_id, verdict=body.verdict, user=user)
    except LookupError as exc:
        raise APIError(404, "not_found", "No such tool-knowledge entry") from exc
    await session.commit()
    return envelope(
        {
            "id": str(entry.id),
            "confidence": round(entry.confidence, 3),
            "confirm_count": entry.confirm_count,
            "reject_count": entry.reject_count,
        }
    )


@router.get("/entries")
async def list_entries(
    _user: CurrentUser,
    session: SessionDep,
    tool: Annotated[ToolFamily, Query()],
    version: Annotated[str | None, Query(max_length=64)] = None,
    surface: Annotated[UiSurface | None, Query()] = None,
    effect: Annotated[ControlEffect | None, Query()] = None,
    control_id: Annotated[str | None, Query(max_length=128)] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_QUERY_LIMIT)] = 50,
) -> dict[str, Any]:
    try:
        rows, meta = await query_entries(
            session,
            tool=tool,
            version=version,
            surface=surface,
            effect=effect,
            control_id=control_id,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise APIError(422, "invalid_version", "version must look like '8.0.6'") from exc
    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            items.append(_serialize_entry(row))
        except ValidationError:
            # A stored row failing CTR-05 re-validation (e.g. after a pattern
            # tightening) must be withheld, and its content must not reach the
            # logs either — id and tool only (review finding).
            logger.warning(
                "toolkb row failed contract re-validation; omitted: id=%s tool=%s",
                row.id,
                row.tool.value,
            )
    return envelope(items, meta=meta)


# --------------------------------------------------------------- TU-09 guides
@router.get("/guides")
async def list_guides_route(
    _user: CurrentUser,
    tool: Annotated[ToolFamily, Query()],
    version: Annotated[str, Query(max_length=64)],
) -> dict[str, Any]:
    """Authored walkthroughs available for a tool+version (unresolved summary)."""
    try:
        guides = list_guides(tool=tool, version=version)
    except ValueError as exc:
        raise APIError(422, "invalid_version", "version must look like '9.0.4'") from exc
    return envelope(
        [
            {
                "id": g.id,
                "tool": g.tool.value,
                "title": g.title,
                "summary": g.summary,
                "step_count": len(g.steps),
            }
            for g in guides
        ]
    )


@router.get("/guides/{guide_id}")
async def get_guide_route(
    guide_id: str,
    _user: CurrentUser,
    session: SessionDep,
    version: Annotated[str, Query(max_length=64)],
) -> dict[str, Any]:
    """One walkthrough, each step resolved against the live KB.

    Both narrations (guide/expert) are returned so the panel switches SOL mode
    (ADR-016) with no round-trip. Unavailable/tentative steps are marked, never
    faked — the renderer degrades gracefully and never shows a confident wrong
    pointer.
    """
    try:
        resolved = await resolve_guide(session, guide_id, version=version)
    except ValueError as exc:
        raise APIError(422, "invalid_version", "version must look like '9.0.4'") from exc
    if resolved is None:
        raise APIError(404, "not_found", "No such guide")
    return envelope(
        {
            "id": resolved.id,
            "tool": resolved.tool.value,
            "title": resolved.title,
            "summary": resolved.summary,
            "steps": [
                {
                    "step_number": s.step_number,
                    "control_id": s.control_id,
                    "entry_id": s.entry_id,
                    "note_guide": s.note_guide,
                    "note_expert": s.note_expert,
                    "available": s.available,
                    "tentative": s.tentative,
                    "stale": s.stale,
                    "label": s.label,
                    "description": s.description,
                    "shortcut": s.shortcut,
                    "menu_path": s.menu_path,
                    "surface": s.surface,
                    "confidence": s.confidence,
                    # SOLUS-TU-10 / SOLX-03: geometry for the overlay. Always
                    # emitted, `null` included — the overlay branches on it, and
                    # a missing key reads as a box at the origin.
                    "locator": s.locator.model_dump() if s.locator else None,
                }
                for s in resolved.steps
            ],
        }
    )
