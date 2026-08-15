"""SOLUS-TU-03 (SOLUSDEV-206) — visual-understanding path [RESEARCH-GRADE].

A spike, not a committed deliverable. Vision over an annotated screenshot
proposes (control, on-screen locator, confidence) for the controls it can see.
Two invariants keep the research path safe:

1. **Model output is untrusted** (CLAUDE.md §7). `parse_vision_output` is a
   firewall: every proposal must be well-shaped, carry a valid control-id slug,
   a 0..1 locator box, and a unit-interval confidence, or it is dropped.
2. **Visual never introduces knowledge, only locates it.** A proposal is only
   ingested if its control is ALREADY a known vendor control (the guard's
   visual path enforces this), it always lands as a CANDIDATE, and it is NEVER
   auto-promoted — an operator must approve it. Below-threshold proposals are
   dropped before ingestion.

Model calls route through the MO-01 gateway (`RouteType.VISUAL_LOG`) — never a
parallel provider stack. Keyless (as on this host) → the extractor returns []
(no signal), mirroring `fingerprint/visual.py`.
"""

import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.contracts.tool_knowledge import ToolFamily
from solus_api.toolkb.guard import IngestContext, IngestRejectedError, ingest
from solus_api.toolkb.schema import AcquisitionMethod

if TYPE_CHECKING:  # pragma: no cover
    from solus_api.orchestration.providers import ImageBlock

logger = logging.getLogger("solus.toolkb.visual")

#: Below this, a proposal is not even offered for review — vision is the
#: weakest ladder rung, so it must clear a bar before consuming attention.
VISUAL_MIN_CONFIDENCE: Final = 0.55
_CONTROL_ID_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_MAX_PROPOSALS: Final = 100

#: The extractor is a callable so tests inject a fake and the real one wraps the
#: MO-01 gateway — vision never has a parallel provider stack.
type VisionModel = Callable[[str, "Sequence[ImageBlock]"], Awaitable[str]]


@dataclass(frozen=True)
class VisualProposal:
    control_id: str
    label: str
    x: float
    y: float
    w: float
    h: float
    confidence: float


@dataclass
class VisualSummary:
    proposed: int = 0
    ingested: int = 0
    below_threshold: int = 0
    rejected: int = 0


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _clean(entry: Any) -> VisualProposal | None:
    """Per-proposal firewall — model output is untrusted (CLAUDE.md §7)."""
    if not isinstance(entry, dict):
        return None
    control_id = entry.get("control_id")
    label = entry.get("label")
    if not isinstance(control_id, str) or not _CONTROL_ID_RE.fullmatch(control_id):
        return None
    if not isinstance(label, str) or not label.strip():
        return None
    coords = [_num(entry.get(k)) for k in ("x", "y", "w", "h")]
    confidence = _num(entry.get("confidence"))
    if any(c is None or not 0.0 <= c <= 1.0 for c in coords) or confidence is None:
        return None
    if not 0.0 <= confidence <= 1.0:
        return None
    x, y, w, h = coords
    return VisualProposal(control_id, label.strip(), x, y, w, h, confidence)  # type: ignore[arg-type]


def parse_vision_output(raw: str) -> list[VisualProposal]:
    """Parse the model's JSON array of proposals, dropping anything malformed."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    cleaned = (_clean(entry) for entry in data[:_MAX_PROPOSALS])
    return [p for p in cleaned if p is not None]


async def ingest_visual_proposals(
    session: AsyncSession,
    proposals: Sequence[VisualProposal],
    *,
    tool: ToolFamily,
    version_range: str,
) -> VisualSummary:
    """Route above-threshold proposals through the guard's visual path.

    The guard rejects any control that is not already documented vendor surface
    and stamps every accepted proposal as a low-confidence CANDIDATE — so visual
    can only LOCATE known controls, never introduce new knowledge, and nothing
    it produces is served until an operator approves it.
    """
    ctx = IngestContext(acquired_via=AcquisitionMethod.VISUAL)
    summary = VisualSummary(proposed=len(proposals))
    for p in proposals:
        if p.confidence < VISUAL_MIN_CONFIDENCE:
            summary.below_threshold += 1
            continue
        entry = {
            "tool": tool.value,
            "version_range": version_range,
            "surface": "toolbar",
            "control_id": p.control_id,
            "label": p.label,
            "effect": "select",
            "description": p.label,
            "invocation": None,
            "locator": {"x": p.x, "y": p.y, "w": p.w, "h": p.h},
            "provenance": "observed_ui",
        }
        try:
            await ingest(session, entry=entry, ctx=ctx)
            summary.ingested += 1
        except IngestRejectedError:
            summary.rejected += 1  # unknown control / customer-shaped content
    logger.info(
        "toolkb visual: proposed=%d ingested=%d below_threshold=%d rejected=%d",
        summary.proposed,
        summary.ingested,
        summary.below_threshold,
        summary.rejected,
    )
    return summary


_PROMPT: Final = (
    "You are shown a screenshot of a CAD/EDA tool's UI. For each toolbar or menu "
    "control you can identify, return a JSON array of objects with: control_id (a "
    "lowercase dotted slug you are confident maps to a documented command, e.g. "
    "kicad.eeschema.place_wire), label (the on-screen text), x/y/w/h (the control's "
    "bounding box as fractions 0..1 of the window), and confidence (0..1). Only "
    "include controls you can actually see. Return ONLY the JSON array."
)
_MAX_ANSWER_TOKENS: Final = 1500


def build_vision_extractor(
    *,
    secret_store: Any,
    user_id: uuid.UUID,
    session: AsyncSession,
    redis: Any = None,
    enqueue: Any = None,
    config: Any = None,
) -> "Callable[[Sequence[ImageBlock]], Awaitable[list[VisualProposal]]]":
    """Wrap the MO-01 gateway into an extractor. Never raises; keyless → []."""

    async def _extract(images: "Sequence[ImageBlock]") -> list[VisualProposal]:
        from solus_api.orchestration import Complexity, RouteType, complete

        try:
            completion = await complete(
                _PROMPT,
                secret_store=secret_store,
                complexity=Complexity.STANDARD,
                type=RouteType.VISUAL_LOG,
                images=list(images),
                config=config,
                user_id=user_id,
                session=session,
                redis=redis,
                enqueue=enqueue,
                max_tokens=_MAX_ANSWER_TOKENS,
            )
        except Exception:  # noqa: BLE001 — vision is best-effort, never load-bearing
            logger.warning("visual extraction failed; treating as no-signal", exc_info=True)
            return []
        return parse_vision_output(completion.text)

    # ponytail: build_vision_extractor is thin gateway glue, exercised end-to-end
    # only with a real VLM key (absent on this host). The firewall + guard routing
    # — the parts that decide what reaches the store — are what the tests pin.
    # This is a spike, not a committed deliverable (see the completion report).
    return _extract
