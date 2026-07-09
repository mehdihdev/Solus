"""Multimodal fingerprint OUTPUT contract (SOLUS-W0-06).

The fingerprint matcher groups one physical part observed across DIFFERENT MODALITIES
(part number, datasheet, schematic symbol, CAD model, photo) into ONE canonical part.
This module is the SHAPE that output takes — nothing more. It is the mock-and-swap seam:
cross-domain linking (LNK-01) builds against the committed mock (`load_mock_output`) now;
the real matcher (FP-01/02) must later produce EXACTLY this shape.

Linking consumes the output to connect cross-domain observations of one part to a single
canonical entity via `graph_entity.canonical_part_id` + a `SAME_AS` edge (ADR-001/012/027).
This module does NOT match anything and does NOT touch the graph — it is data shapes only.
"""

import enum
from pathlib import Path
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Modality(enum.StrEnum):
    """How a single part was observed. `PHOTO` is declared-but-optional: the shape carries
    it so the contract is stable when visual matching arrives, but the v1 matcher does not
    populate it (visual matching is a later stretch)."""

    PART_NUMBER = "part_number"
    DATASHEET = "datasheet"
    SCHEMATIC_SYMBOL = "schematic_symbol"
    CAD_MODEL = "cad_model"
    PHOTO = "photo"


class MatchState(enum.StrEnum):
    """The state of ONE observation's match to a canonical part. UNMATCHED is NOT a state
    here — unmatched observations are represented explicitly at the top level via
    `FingerprintOutput.unmatched`, so linking has a definitive list (never inferred by
    absence)."""

    MATCHED = "matched"  # above threshold, confident
    LOW_CONFIDENCE = "low_confidence"  # present but flagged; linking chooses to include/exclude


class SourceRef(BaseModel):
    """How a match resolves back to an actual `graph_entity` observation — the mechanism
    linking depends on. Linking maps each match to the specific observation so it can set
    `canonical_part_id` on that entity / create the `SAME_AS` edge. Mirrors the
    `graph_entity` provenance columns (`source_connector`, `external_ref`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    graph_entity_id: UUID | None = None  # the observation's graph_entity id, if already ingested
    source_connector: str | None = None  # mirrors graph_entity.source_connector
    external_ref: str | None = None  # mirrors graph_entity.external_ref (id in the source tool)

    @model_validator(mode="after")
    def _require_resolvable(self) -> Self:
        """At least one of `graph_entity_id` OR (`source_connector` AND `external_ref`) must
        be present, so linking can always resolve the observation."""
        if self.graph_entity_id is None and not (self.source_connector and self.external_ref):
            raise ValueError(
                "SourceRef must be resolvable: provide graph_entity_id, or both "
                "source_connector and external_ref"
            )
        return self


class ModalityMatch(BaseModel):
    """One observation matched to a canonical part."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    modality: Modality
    source_ref: SourceRef  # ties this match back to a real graph_entity observation
    confidence: float = Field(ge=0, le=1)  # how sure THIS observation is THIS part
    state: MatchState
    # Structured-but-flexible: WHAT matched and HOW, e.g.
    # {"matched_on": "part_number", "value": "LM358", "note": "exact string match"}.
    # For debugging and for SOL to later explain WHY things were linked.
    evidence: dict[str, Any] = Field(default_factory=dict)


class CanonicalPart(BaseModel):
    """One physical part plus every modality matched to it. `confidence` is the OVERALL
    confidence this grouping is correct — separate from per-match confidence, so linking can
    accept a part overall yet reject a shaky modality within it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical_id: UUID  # the canonical entity identity (maps to a CANONICAL_PART graph_entity)
    part_number: str | None = None
    manufacturer: str | None = None
    datasheet_ref: str | None = None
    modalities: list[ModalityMatch]
    confidence: float = Field(ge=0, le=1)


class AmbiguousObservation(BaseModel):
    """An observation that partially matched >1 part or fell between thresholds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_ref: SourceRef
    candidate_canonical_ids: list[UUID]  # the canonical parts it might belong to
    note: str | None = None


class FingerprintOutput(BaseModel):
    """The full matcher output: successful groupings PLUS explicit unmatched/ambiguous. The
    three states are always emitted explicitly (never inferred by absence) so linking can
    threshold: MATCHED / LOW_CONFIDENCE (inside `canonical_parts[].modalities`), UNMATCHED
    (`unmatched`), AMBIGUOUS (`ambiguous`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical_parts: list[CanonicalPart]  # successful groupings
    unmatched: list[SourceRef]  # observations the matcher could NOT confidently assign
    ambiguous: list[AmbiguousObservation]  # partially matched >1 part / between thresholds


_MOCK_PATH = Path(__file__).with_name("mock_canonical_parts.json")


def load_mock_output(path: Path | None = None) -> FingerprintOutput:
    """Load + validate the committed mock — the mock-and-swap seam entry point. Linking
    (LNK-01) calls this today; the real matcher (FP-01/02) will produce the same shape later.
    Defaults to the sibling `mock_canonical_parts.json`."""
    return FingerprintOutput.model_validate_json((path or _MOCK_PATH).read_text())
