"""Bounded extraction candidates, never graph assignments or permission to acquire data.

Adapters supply already-authorized observations. Validation preserves original strings and
contradictions, canonicalizing only exact record duplicates and collection ordering.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Annotated, Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_ROWS: Final = 256
MAX_PROVENANCE: Final = 32
MAX_NOTES: Final = 32
MAX_BATCH_BYTES: Final = 256 * 1024

Reference = Annotated[str, Field(min_length=1, max_length=512)]
Detail = Annotated[str, Field(min_length=1, max_length=2048)]
SourceKind = Literal["firmware", "host_config", "onboard", "schematic"]
ExtractionStatus = Literal["success", "unavailable", "invalid"]


class _FrozenEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)


def _bounded_items(value: object, limit: int) -> tuple[Any, ...]:
    # Check raw count before exact-duplicate reduction, and never consume an unbounded iterator.
    if not isinstance(value, (list, tuple)) or len(value) > limit:
        raise ValueError(f"expected at most {limit} items in a list or tuple")
    return tuple(value)


def _canonical[Model: BaseModel](values: tuple[Model, ...]) -> tuple[Model, ...]:
    keyed = {item.model_dump_json(): item for item in values}
    return tuple(keyed[key] for key in sorted(keyed))


def _json_model(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError("only structured evidence values are supported")


class TopologyProvenance(_FrozenEvidence):
    """A source observation and optional exact component/pin reference; not inferred wiring."""

    source_ref: Reference
    entity_ref: Reference | None = None
    pin_ref: Reference | None = None
    detail: Detail | None = None


class TopologyEvidence(_FrozenEvidence):
    """One candidate association. None expresses unknown; incompatible candidates stay separate."""

    source_namespace: Annotated[str, Field(min_length=1, max_length=128)]
    source_ref: Reference
    bus: Reference | None = None
    device: Reference | None = None
    protocol: Reference | None = None
    address: Reference | None = None
    part_candidate: Reference | None = None
    provenance: tuple[TopologyProvenance, ...] = ()
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None

    @field_validator("provenance", mode="before")
    @classmethod
    def _limit_provenance(cls, value: object) -> tuple[Any, ...]:
        return _bounded_items(value, MAX_PROVENANCE)

    @field_validator("provenance")
    @classmethod
    def _normalize_provenance(
        cls, value: tuple[TopologyProvenance, ...]
    ) -> tuple[TopologyProvenance, ...]:
        return _canonical(value)

    @model_validator(mode="after")
    def _confidence_has_observation(self) -> Self:
        if self.confidence is not None and not self.provenance:
            raise ValueError("confidence requires supporting provenance")
        return self


def _validate_payload_items(value: Mapping[str, Any]) -> None:
    if value.keys() - {"source_kind", "status", "rows", "notes"}:
        raise ValueError("unexpected extraction fields")
    for field in ("source_kind", "status"):
        header = value.get(field)
        if not isinstance(header, str) or len(header) > 128:
            raise ValueError("invalid extraction header")
    for field, limit in (("rows", MAX_ROWS), ("notes", MAX_NOTES)):
        if field in value:
            _bounded_items(value[field], limit)
    # Reject nested counts/types/strings before encoding. Encode the original
    # input below so duplicate evidence still consumes the raw input budget.
    for row in value.get("rows", ()):
        TopologyEvidence.model_validate(row)
    for note in value.get("notes", ()):
        if not isinstance(note, str) or not 1 <= len(note) <= 2048:
            raise ValueError("invalid extraction note")


class TopologyExtraction(_FrozenEvidence):
    """One source adapter result; failed acquisition/validation is distinct from zero findings."""

    source_kind: SourceKind
    status: ExtractionStatus
    rows: tuple[TopologyEvidence, ...] = ()
    notes: tuple[Detail, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _limit_payload(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            _validate_payload_items(value)
            try:
                encoder = json.JSONEncoder(
                    default=_json_model,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
                size = 0
                for chunk in encoder.iterencode(dict(value)):
                    size += len(chunk.encode("utf-8"))
                    if size > MAX_BATCH_BYTES:
                        raise ValueError(
                            f"extraction exceeds {MAX_BATCH_BYTES} bytes before normalization"
                        )
            except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
                raise ValueError(
                    "extraction must contain bounded JSON-compatible evidence"
                ) from exc
        return value

    @field_validator("rows", mode="before")
    @classmethod
    def _limit_rows(cls, value: object) -> tuple[Any, ...]:
        return _bounded_items(value, MAX_ROWS)

    @field_validator("rows")
    @classmethod
    def _normalize_rows(cls, value: tuple[TopologyEvidence, ...]) -> tuple[TopologyEvidence, ...]:
        return _canonical(value)

    @field_validator("notes", mode="before")
    @classmethod
    def _limit_notes(cls, value: object) -> tuple[Any, ...]:
        return _bounded_items(value, MAX_NOTES)

    @field_validator("notes")
    @classmethod
    def _normalize_notes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(value)))

    @model_validator(mode="after")
    def _status_matches_rows(self) -> Self:
        if self.status != "success" and self.rows:
            raise ValueError("unavailable or invalid extraction cannot contain candidate rows")
        return self
