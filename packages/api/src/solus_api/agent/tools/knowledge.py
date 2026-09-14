"""Tool knowledge in the SOL loop (SOLUSDEV-251 / INTEGRATIONS I4; ADR-033).

Two small seams, both over the GLOBAL, tenant-free tool-knowledge table:

* **Notes** — for a write tool that acts on a documented UI control (the map
  below), the published vendor-documentation entry reaches the model as one
  fenced data block appended to that tool's description, so SOL behaves the
  way the TOOL works ("KiCad: Symbol Properties edits a symbol's fields") rather
  than generically. Only `published` rows are read — never candidates, never
  anything project-scoped — and the note is capped and framed as data.
* **Outcomes** — after a confirmed write actually runs, its result is one more
  observation on that control: `confirm` when the tool did what the note said,
  `reject` when it refused. That is the correction loop the ticket asks for,
  through the ONLY tool-knowledge write path (`toolkb.feedback` → the guard).

Never raises: a missing entry, an unmapped tool, or a table hiccup is a no-op
with a log line — the model still gets the tool, just without the note.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode, ToolResult
from solus_api.contracts.tool_knowledge import Provenance, ToolFamily
from solus_api.models import User
from solus_api.toolkb.feedback import apply_feedback
from solus_api.toolkb.schema import AcquisitionMethod, Verdict
from solus_api.toolkb.storage import query_entries

logger = logging.getLogger("solus.agent.knowledge")

#: Write tool → the vendor-documented UI control it acts on. Control ids are the
#: vendor's own names (the seed catalogs under `toolkb/catalog/`); adding a row
#: here is a data change, never a new mechanism.
TOOL_CONTROLS: Final[dict[str, tuple[ToolFamily, str]]] = {
    "isaac.start": (ToolFamily.ISAAC, "isaac.standalone.application"),
    "code.git_commit": (ToolFamily.CODE, "code.git.commit"),
    "code.git_push": (ToolFamily.CODE, "code.git.push"),
    "code.arduino_prepare": (ToolFamily.CODE, "code.arduino.core_install"),
    "code.arduino_compile": (ToolFamily.CODE, "code.arduino.compile"),
    "kicad.set_symbol_property": (ToolFamily.KICAD, "kicad.eeschema.edit_symbol_properties"),
    "kicad.add_symbol": (ToolFamily.KICAD, "kicad.eeschema.interactive_drawing.place_symbol"),
    "kicad.add_wire": (
        ToolFamily.KICAD,
        "kicad.eeschema.interactive_drawing_line_wire_bus.draw_wires",
    ),
    "kicad.add_net_label": (ToolFamily.KICAD, "kicad.eeschema.interactive_drawing.place_label"),
    "kicad.mark_no_connect": (
        ToolFamily.KICAD,
        "kicad.eeschema.interactive_drawing.place_no_connect",
    ),
    "onshape.set_variable": (ToolFamily.ONSHAPE, "onshape.partstudio.variable_table"),
    "onshape.add_feature": (ToolFamily.ONSHAPE, "onshape.partstudio.feature_list"),
    "onshape.update_feature": (ToolFamily.ONSHAPE, "onshape.partstudio.feature_list"),
}

NOTE_CAP: Final = 400
#: Only vendor documentation, admitted through the docs path and still trusted,
#: may reach a prompt (security review C1): never a community candidate that
#: cleared the publish bar, never a low-confidence row.
NOTE_CONFIDENCE_FLOOR: Final = 0.6
_NOTE_CANDIDATES: Final = 5
#: Tool error codes that say nothing about the CONTROL (transport, entitlement,
#: throttling): the vote abstains (security review H1).
_ABSTAIN_CODES: Final = frozenset(
    {
        ToolErrorCode.UNAVAILABLE,
        ToolErrorCode.TIMEOUT,
        ToolErrorCode.UNAUTHORIZED,
    }
)


@dataclass(frozen=True)
class KnowledgeNote:
    control_id: str
    text: str


def _trusted(entry: Any) -> bool:
    return (
        entry.acquired_via is AcquisitionMethod.DOCS
        and entry.provenance is Provenance.VENDOR_DOCS
        and float(entry.confidence) >= NOTE_CONFIDENCE_FLOOR
    )


async def load_knowledge_notes(
    session: AsyncSession, *, versions: Mapping[ToolFamily, str] | None = None
) -> dict[str, KnowledgeNote]:
    """One note per mapped tool that has a PUBLISHED, vendor-docs, trusted entry
    (and, when the connected tool's version is known, one whose range covers
    it); empty beats invented."""
    notes: dict[str, KnowledgeNote] = {}
    for tool_name, (family, control_id) in TOOL_CONTROLS.items():
        version = (versions or {}).get(family)
        try:
            entries, _ = await query_entries(
                session,
                tool=family,
                control_id=control_id,
                version=version,
                limit=_NOTE_CANDIDATES,
            )
        except Exception:  # noqa: BLE001 — a note is an optional aid, never a failure
            logger.warning("tool knowledge lookup failed for %s", tool_name)
            continue
        entry = next((e for e in entries if _trusted(e)), None)
        if entry is None:
            continue
        text = f"{entry.label}: {entry.description}"
        if entry.shortcut:
            text += f" Default shortcut: {entry.shortcut}."
        text = text[:NOTE_CAP]
        notes[tool_name] = KnowledgeNote(control_id=control_id, text=text)
    return notes


def with_knowledge_notes(
    descriptors: Sequence[ToolDescriptor], notes: Mapping[str, KnowledgeNote]
) -> tuple[ToolDescriptor, ...]:
    """Descriptors carrying each mapped tool's note in `knowledge_note` — a
    separate field that prompt assembly renders as its OWN fenced block, so the
    note is never inside a vendor description's fence and never prose."""
    out: list[ToolDescriptor] = []
    for descriptor in descriptors:
        note = notes.get(descriptor.name)
        if note is None:
            out.append(descriptor)
            continue
        out.append(
            descriptor.model_copy(
                update={"knowledge_note": f"[{note.control_id}] {note.text}"[: NOTE_CAP + 160]}
            )
        )
    return tuple(out)


def _code_verdict(result: ToolResult) -> Verdict | None:
    """Repository/build failures do not contradict vendor documentation."""
    value = result.value or {}
    if not result.ok or value.get("ok") is not True:
        return None
    if any(value.get(flag) for flag in ("uncertain", "timed_out", "dry_run")):
        return None
    if "exit_code" in value:
        exit_code = value["exit_code"]
        if type(exit_code) is not int or exit_code != 0:
            return None
    return Verdict.CONFIRM


def write_verdict(tool_name: str, result: ToolResult) -> Verdict | None:
    """What a confirmed write's result says about the CONTROL: CONFIRM when it
    landed, REJECT when the tool itself refused the change, None (abstain) when
    the failure was transport, entitlement or throttling — those say nothing
    about the vendor's documentation (security review H1)."""
    mapped = TOOL_CONTROLS.get(tool_name)
    if mapped is not None and mapped[0] is ToolFamily.CODE:
        return _code_verdict(result)
    if result.ok:
        value = result.value if isinstance(result.value, dict) else {}
        if tool_name.startswith("kicad."):
            return Verdict.CONFIRM if value.get("changed") is True else Verdict.REJECT
        return Verdict.CONFIRM
    code = result.error.code if result.error is not None else None
    if code is None or code in _ABSTAIN_CODES:
        return None
    return Verdict.REJECT


def write_succeeded(tool_name: str, result: ToolResult) -> bool:
    """Whether a confirmed write actually LANDED (a fork may report a refusal as
    `ok` with `changed: false` — the KiCad write does)."""
    return write_verdict(tool_name, result) is Verdict.CONFIRM


async def record_write_outcome(
    session: AsyncSession,
    *,
    tool_name: str,
    result: ToolResult,
    user: User,
    team_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> None:
    """A confirmed write ran: vote on the control it acts on. No entry, an
    unmapped tool, or a transport failure → no vote, never an error."""
    mapped = TOOL_CONTROLS.get(tool_name)
    if mapped is None:
        return
    verdict = write_verdict(tool_name, result)
    if verdict is None:
        return
    family, control_id = mapped
    try:
        entries, _ = await query_entries(
            session, tool=family, control_id=control_id, limit=_NOTE_CANDIDATES
        )
        entry = next((e for e in entries if _trusted(e)), None)
        if entry is None:
            return
        await apply_feedback(
            session,
            entry_id=entry.id,
            verdict=verdict,
            user=user,
            team_id=team_id,
            project_id=project_id,
        )
        logger.info("tool knowledge %s recorded for %s", verdict.value, tool_name)
    except Exception:  # noqa: BLE001 — feedback never fails the action that ran
        logger.warning("tool knowledge feedback failed for %s", tool_name)
