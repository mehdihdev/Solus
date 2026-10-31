"""SOLUSDEV-321 P5 — the graph's numbers win over a render's read (R103).

A render shows what is drawn; the graph states what is true. `vision_postcheck` compares each length
a read names for a labelled part with the extents the graph states for that part, and the graph's
value wins:

- **Facts.** Only what the graph states: `attrs.geometry.dimensions` with its `length_unit` (mm or
  m), the bounding-box extents a CAD import measures (`length_fact`). An entity without them is
  not checked: empty beats invented.
- **Tokens.** P2-T6's own grounding comparison (`agent/finding_narration.py`): a number in prose
  with the unit word after it, compared as a number, to the digits it is written to, in its own
  unit (an extent is converted into the read's unit first). Never a substring search: `30` is not
  `300`.
- **Attribution.** A sentence is checked only when it names exactly one labelled part (its label,
  as whole words): a sentence about two parts, or none, says nothing checkable about one.
- **The graph wins.** A length that rounds to none of the part's extents is replaced in the text
  by the nearest extent the graph states, in the graph's unit, with the render's value in
  brackets. Each part's first such length is its `Disagreement`.
- **One finding.** `file_disagreements` raises ONE `vision_fact_disagreement` info finding per
  (entity, length) per render through `raise_finding` (`source: "sol"`, `bucket: "length"`, so a
  later render of the same disagreement counts on the same row). Its evidence is parsed numbers,
  their units and the view: the read's text, model output, never reaches it.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from solus_api.agent.finding_narration import _NUMBER, _rounds_to, _spoken_unit
from solus_api.checkers.interface import Severity
from solus_api.graph.findings import FindingSpec, raise_finding
from solus_api.models import Domain

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from solus_api.agent.interfaces import EntityRead

RULE_ID: Final = "vision_fact_disagreement"
QUANTITY: Final = "length"
#: The units a length is checked in — as P2-T6's tokens spell them — in millimetres.
LENGTH_UNITS_MM: Final[Mapping[str, float]] = MappingProxyType({"mm": 1.0, "m": 1000.0})
MAX_EXTENTS: Final = 3
#: Where one sentence ends: punctuation, then space (so the point inside `0.04` is no end).
_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True, slots=True)
class LengthFact:
    """The extents the graph states for one labelled part, in millimetres, and the unit it states
    them in."""

    entity_id: uuid.UUID
    label: str
    domain: str
    extents_mm: tuple[float, ...]
    unit: str


@dataclass(frozen=True, slots=True)
class Disagreement:
    """A length the read gave for `fact`'s part that the graph states differently: the read's
    number and unit, and the graph's nearest extent in the graph's own unit."""

    fact: LengthFact
    render_value: float
    render_unit: str
    graph_value: float


@dataclass(frozen=True, slots=True)
class PostCheck:
    """The read with the graph's values in, and each part's first disagreement."""

    text: str
    disagreements: tuple[Disagreement, ...]


def length_fact(entity: EntityRead) -> LengthFact | None:
    """The extents the graph states for `entity` (module docstring), or None."""
    geometry = entity.attrs.get("geometry")
    if not isinstance(geometry, Mapping):
        return None
    unit, dimensions = geometry.get("length_unit"), geometry.get("dimensions")
    if not isinstance(unit, str) or unit not in LENGTH_UNITS_MM:
        return None
    if not isinstance(dimensions, list):
        return None
    if not 1 <= len(dimensions) <= MAX_EXTENTS or not all(map(_positive_length, dimensions)):
        return None
    scale = LENGTH_UNITS_MM[unit]
    extents = tuple(float(value) * scale for value in dimensions)
    return LengthFact(entity.id, entity.name, entity.domain, extents, str(unit))


def vision_postcheck(text: str, facts: Sequence[LengthFact]) -> PostCheck:
    """`text` with every length the graph states differently replaced by the graph's value, and
    each part's first disagreement (module docstring)."""
    found: dict[uuid.UUID, Disagreement] = {}
    pieces: list[str] = []
    for sentence in _sentences(text):
        named = [fact for fact in facts if _names_part(sentence, fact.label)]
        pieces.append(_graph_wins_in(sentence, named[0], found) if len(named) == 1 else sentence)
    return PostCheck("".join(pieces), tuple(found.values()))


async def file_disagreements(
    session: AsyncSession,
    project_id: uuid.UUID,
    disagreements: Sequence[Disagreement],
    *,
    view_id: str,
) -> list[uuid.UUID]:
    """ONE info finding per (entity, length) of this render, through `raise_finding`. Flushes;
    the caller commits."""
    ids: list[uuid.UUID] = []
    for disagreement in {d.fact.entity_id: d for d in reversed(disagreements)}.values():
        fact = disagreement.fact
        row = await raise_finding(
            session,
            project_id,
            FindingSpec(
                rule_id=RULE_ID,
                severity=Severity.INFO,
                source="sol",
                headline=(
                    f"a render read {fact.label}'s {QUANTITY} as "
                    f"{disagreement.render_value:g} {disagreement.render_unit}; "
                    f"the graph states {disagreement.graph_value:g} {fact.unit}"
                ),
                subjects=[fact.entity_id],
                evidence=_parsed_evidence(disagreement, view_id),
                domain=Domain(fact.domain),
                bucket=QUANTITY,
            ),
        )
        ids.append(row.id)
    return ids


def _parsed_evidence(disagreement: Disagreement, view_id: str) -> dict[str, Any]:
    """Parsed numbers, their units, the quantity and the view: never the read's text."""
    return {
        "quantity": QUANTITY,
        "graph": {"value": disagreement.graph_value, "unit": disagreement.fact.unit},
        "render": {"value": disagreement.render_value, "unit": disagreement.render_unit},
        "view": view_id,
    }


def _positive_length(value: object) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _sentences(text: str) -> Iterator[str]:
    """`text` in sentences, each with the space that ends it, so joining them gives `text`."""
    start = 0
    for end in _SENTENCE_END.finditer(text):
        yield text[start : end.end()]
        start = end.end()
    yield text[start:]


def _names_part(sentence: str, label: str) -> bool:
    """Whether `sentence` names `label` as whole words, case aside."""
    pattern = rf"(?<!\w){re.escape(label.casefold())}(?!\w)"
    return bool(label.strip()) and re.search(pattern, sentence.casefold()) is not None


def _graph_wins_in(sentence: str, fact: LengthFact, found: dict[uuid.UUID, Disagreement]) -> str:
    """`sentence` with each length `fact`'s extents do not ground replaced by the graph's."""
    pieces, last = [], 0
    for match in _NUMBER.finditer(sentence):
        unit = _spoken_unit(match.group(2)) if match.group(2) else None
        if unit is None or unit not in LENGTH_UNITS_MM:
            continue
        token, scale = Decimal(match.group(1)), LENGTH_UNITS_MM[unit]
        # P5 fix 1 (M1): `1e999` parses but is no float, so it is no length to disagree with.
        if not math.isfinite(float(token)) or any(
            _rounds_to(token, extent / scale) for extent in fact.extents_mm
        ):
            continue
        read_mm = float(token) * scale
        nearest = min(fact.extents_mm, key=lambda extent: abs(extent - read_mm))
        graph_value = nearest / LENGTH_UNITS_MM[fact.unit]
        found.setdefault(fact.entity_id, Disagreement(fact, float(token), unit, graph_value))
        shown = f"{graph_value:g} {fact.unit} (the graph's value; the render read {token} {unit})"
        pieces += [sentence[last : match.start()], shown]
        last = match.end()
    return "".join(pieces) + sentence[last:]
