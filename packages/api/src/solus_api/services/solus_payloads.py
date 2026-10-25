"""Typed `.solus` entry payloads (docs/api/solus.md §2.1, SOLUSDEV-320).

`solus_entries.payload` is never free-form JSON: each (section, subsection) that carries one
names its Pydantic model here. `ErrorMeta` is filed by `resolve_finding` and
`agent/errors_filing.py`; `GoalMeta` and `ConstraintMeta` are set through
`PATCH …/entries/{id}/payload` (§3.2). Member/environment config models arrive with
their writers (P5).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from solus_api.core.errors import APIError

#: Per-entry bound on linked/scoped id lists; the ids are references, not an index.
MAX_LINKED_IDS: Final = 64


class ErrorMeta(BaseModel):
    """Metadata of one `errors` entry: what it blames, how often, and whether it is fixed."""

    model_config = ConfigDict(extra="forbid")

    entity_id: uuid.UUID | None = None
    machine_id: uuid.UUID | None = None
    dedupe_key: str = Field(pattern=r"^[0-9a-f]{40}$")
    count: int = Field(ge=1)
    status: Literal["open", "resolved", "recurring"]
    fix_ref: uuid.UUID | None = None
    first_seen: datetime
    last_seen: datetime


class GoalMeta(BaseModel):
    """Metadata of one `goals` entry: its status, owner and what it is linked to."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["open", "met", "dropped"] = "open"
    owner: uuid.UUID | None = None
    linked_conversation_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=MAX_LINKED_IDS
    )
    linked_entity_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_LINKED_IDS)
    linked_run_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_LINKED_IDS)


#: `SourcingRules.MAX_LIST` / `Short`: a compliance entry's supplier and certification lists
#: are bounded like the rules document they merge into.
MAX_SOURCING_NAMES: Final = 32
SourcingName = Annotated[str, Field(min_length=1, max_length=80)]


class ConstraintMeta(BaseModel):
    """A constraint (`constraints/{rules,compliance,style}`): optionally a quantified bound
    (all four of quantity/limit/unit/comparator, or none — half a bound is 422), its scope,
    the entry it was derived from, and — on `compliance` entries — the suppliers to exclude
    and certifications to require, which `sourcing.service.load_rules` merges (P5-T5)."""

    model_config = ConfigDict(extra="forbid")

    quantity: str | None = Field(default=None, min_length=1, max_length=128)
    limit: float | None = Field(default=None, allow_inf_nan=False)  # JSONB has no NaN token
    unit: str | None = Field(default=None, max_length=32)
    comparator: Literal["<", "<=", "=", ">=", ">"] | None = None
    scope_entity_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_LINKED_IDS)
    source_entry_id: uuid.UUID | None = None
    excluded_suppliers: list[SourcingName] = Field(
        default_factory=list, max_length=MAX_SOURCING_NAMES
    )
    required_certifications: list[SourcingName] = Field(
        default_factory=list, max_length=MAX_SOURCING_NAMES
    )

    @model_validator(mode="after")
    def _bound_all_or_none(self) -> Self:
        bound = (self.quantity, self.limit, self.unit, self.comparator)
        if any(v is None for v in bound) and any(v is not None for v in bound):
            raise ValueError("a quantified constraint needs quantity, limit, unit and comparator")
        return self

    @property
    def is_quantified(self) -> bool:
        return self.quantity is not None


BudgetStatus = Literal["ok", "exceeded", "unknown"]


class BudgetLine(BaseModel):
    """One budget (`power:<rail>`, `mass`, `cost`); `current`/`limit` are null when the graph
    does not state them — the UI says "no limit known", never a guess (P5-T6)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=96)
    current: float | None = Field(default=None, allow_inf_nan=False)
    limit: float | None = Field(default=None, allow_inf_nan=False)
    unit: str = Field(max_length=16)
    source: str = Field(max_length=200)
    status: BudgetStatus


class Budgets(BaseModel):
    """`constraints/budgets` CONFIG (`services/budgets.py`, system)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    computed_at: datetime
    budgets: list[BudgetLine] = Field(default_factory=list, max_length=256)


#: The desktop's `PreferenceSection` keys (shared-types/engineering-preferences.ts). The
#: desktop sends each shared section as its text; `freeText` never leaves the machine.
PreferenceSection = Literal[
    "codeStyle", "mechanical", "electrical", "documentation", "unitsStandards"
]
MAX_PREFERENCES_BYTES: Final = 32 * 1024


class MemberPreferences(BaseModel):
    """`members/<uid.hex>` CONFIG: only the sections the member flagged as shared."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    shared: dict[PreferenceSection, str]

    @model_validator(mode="after")
    def _size_bound(self) -> Self:
        if sum(len(text.encode()) for text in self.shared.values()) > MAX_PREFERENCES_BYTES:
            raise ValueError(f"shared preferences exceed {MAX_PREFERENCES_BYTES} bytes")
        return self


class SpecPackage(BaseModel):
    """One package the graph says the project needs; `specifier` is transcribed from the
    requirement entity, never guessed (null when the manifest pinned nothing)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    ecosystem: str = Field(min_length=1, max_length=32)
    specifier: str | None = Field(default=None, max_length=128)
    required_by: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_LINKED_IDS)
    source: Literal["manifest", "config"]


class SpecTool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    version: str | None = Field(default=None, max_length=64)


class EnvironmentSpec(BaseModel):
    """`environment/spec` CONFIG (`services/environment_spec.py`)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    computed_at: datetime
    packages: list[SpecPackage] = Field(default_factory=list, max_length=2000)
    tools: list[SpecTool] = Field(default_factory=list, max_length=64)


DivergenceCause = Literal["missing", "version_drift", "platform_build", "extra"]


class DivergenceItem(BaseModel):
    """Wire twin of the desktop's `DivergenceItem` (lib/api/environment.ts)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    expected: str | None = Field(default=None, max_length=200)
    actual: str | None = Field(default=None, max_length=200)
    detail: str | None = Field(default=None, max_length=200)


class DivergenceGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cause: DivergenceCause
    items: list[DivergenceItem] = Field(max_length=2000)


class MachineDivergences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: uuid.UUID
    hostname: str = Field(max_length=128)
    causes: list[DivergenceGroup] = Field(default_factory=list, max_length=4)


class EnvironmentDivergencesDoc(BaseModel):
    """`environment/divergences` CONFIG (`services/environment_divergence.py`); the wire
    shape of `GET /projects/{id}/environment/divergences`."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    computed_at: datetime
    spec_entry_id: uuid.UUID | None
    machines: list[MachineDivergences] = Field(default_factory=list, max_length=500)


def payload_unchanged(
    stored: Mapping[str, Any] | None, fresh: Mapping[str, Any], ignore: tuple[str, ...] = ()
) -> bool:
    """True when `fresh` equals the stored document apart from the `ignore`d top-level keys
    (a recompute timestamp alone is not a change worth a version)."""
    if stored is None:
        return False
    return {k: v for k, v in stored.items() if k not in ignore} == {
        k: v for k, v in fresh.items() if k not in ignore
    }


#: (section, subsection) → payload model. `None` subsection = the whole section.
PAYLOAD_MODELS: Final[dict[tuple[str, str | None], type[BaseModel]]] = {
    ("goals", None): GoalMeta,
    ("constraints", "rules"): ConstraintMeta,
    ("constraints", "compliance"): ConstraintMeta,
    ("constraints", "style"): ConstraintMeta,
    ("errors", None): ErrorMeta,
    ("environment", "spec"): EnvironmentSpec,
    ("environment", "divergences"): EnvironmentDivergencesDoc,
    ("members", None): MemberPreferences,  # every `<uid.hex>` subsection
}


def validate_entry_payload(
    section: str, subsection: str | None, kind: str, payload: Mapping[str, Any]
) -> BaseModel:
    """The validated payload for an entry, or 422. `kind` is the entry kind (text/sol/...);
    today every registered model applies to all kinds of its section."""
    model = PAYLOAD_MODELS.get((section, subsection)) or PAYLOAD_MODELS.get((section, None))
    if model is None:
        raise APIError(
            422, "validation_error", f"No payload is defined for {section}/{subsection or '*'}"
        )
    try:
        return model.model_validate(dict(payload))
    except ValidationError as exc:
        raise APIError(
            422, "validation_error", f"Invalid {kind} payload: {exc.errors()[0]['msg']}"
        ) from exc
