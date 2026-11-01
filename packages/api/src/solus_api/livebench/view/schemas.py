"""Strict shapes for the team-shared bench view (docs/api/bench-view.md §1–§3,
docs/schemas/bench-view.md). Unknown fields are rejected at every level."""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    model_serializer,
    model_validator,
)

from solus_api.core.errors import APIError

MAX_OPS: Final = 32
MAX_ORDER: Final = 1023
MAX_LIMIT_MAGNITUDE: Final = 1e12
MAX_UNIT_CHARS: Final = 32
MAX_NAME_CHARS: Final = 64
MAX_GROUP_CHARS: Final = 64
#: Bounded walk over a PATCH body looking for NaN/Infinity (a JSON body can carry them).
_MAX_INPUT_ITEMS: Final = 20_000

#: Reference charset: printable ASCII 0x20–0x7E except `"` and `\` (route doc §1).
_REF_PATTERN: Final = r"^[\x20\x21\x23-\x5B\x5D-\x7E]+$"


def _printable(value: str) -> str:
    if not value.isprintable():
        raise ValueError("must contain printable characters only")
    return value


DeviceId = Annotated[StrictStr, Field(min_length=1, max_length=512, pattern=_REF_PATTERN)]
SignalName = Annotated[StrictStr, Field(min_length=1, max_length=128, pattern=_REF_PATTERN)]
PlotGroup = Annotated[
    StrictStr, Field(min_length=1, max_length=MAX_GROUP_CHARS, pattern=_REF_PATTERN)
]
Unit = Annotated[
    StrictStr, Field(min_length=1, max_length=MAX_UNIT_CHARS), AfterValidator(_printable)
]
DerivedName = Annotated[
    StrictStr, Field(min_length=1, max_length=MAX_NAME_CHARS), AfterValidator(_printable)
]
Order = Annotated[StrictInt, Field(ge=0, le=MAX_ORDER)]
LimitValue = Annotated[
    float, Field(strict=True, allow_inf_nan=False, ge=-MAX_LIMIT_MAGNITUDE, le=MAX_LIMIT_MAGNITUDE)
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SignalTarget(_Strict):
    kind: Literal["signal"]
    device_id: DeviceId
    signal: SignalName


class DerivedTarget(_Strict):
    kind: Literal["derived"]
    id: uuid.UUID


Target = Annotated[SignalTarget | DerivedTarget, Field(discriminator="kind")]


def target_key(target: SignalTarget | DerivedTarget) -> tuple[str, ...]:
    """Identity and canonical sort key of a target."""
    if isinstance(target, SignalTarget):
        return ("signal", target.device_id, target.signal)
    return ("derived", str(target.id))


class Limits(_Strict):
    min: LimitValue
    max: LimitValue

    @model_validator(mode="after")
    def _ordered(self) -> Limits:
        if not self.min < self.max:
            raise ValueError("limits.min must be less than limits.max")
        return self


class DisplayPatch(_Strict):
    """Only the fields present are applied; `null` resets a field to its default."""

    pinned: StrictBool | None = None
    hidden: StrictBool | None = None
    order: Order | None = None
    unit: Unit | None = None
    limits: Limits | None = None
    plot_group: PlotGroup | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> DisplayPatch:
        if not self.model_fields_set:
            raise ValueError("patch must set at least one field")
        return self

    @model_serializer(mode="wrap")
    def _present_only(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        dumped: dict[str, Any] = handler(self)
        return {k: v for k, v in dumped.items() if k in self.model_fields_set}


class SetDisplay(_Strict):
    kind: Literal["set_display"]
    target: Target
    patch: DisplayPatch


class UpsertDerived(_Strict):
    kind: Literal["upsert_derived"]
    id: uuid.UUID | None = None
    name: DerivedName
    #: Bounded by the grammar (too_long → expression_error), not here.
    expression: StrictStr
    unit: Unit | None = None


class DeleteDerived(_Strict):
    kind: Literal["delete_derived"]
    id: uuid.UUID


Op = Annotated[SetDisplay | UpsertDerived | DeleteDerived, Field(discriminator="kind")]
_OPS: Final = TypeAdapter(list[Op])


def _reject_non_finite(value: object) -> object:
    # The validation handler echoes rejected inputs; a raw NaN would then fail JSON
    # serialization and turn a bad input into a 500 (as services/workspace_layout.py).
    pending = [value]
    visited = 0
    while pending:
        item = pending.pop()
        visited += 1
        if visited > _MAX_INPUT_ITEMS:
            raise APIError(422, "validation_error", "Bench view input is too large")
        if isinstance(item, float) and not math.isfinite(item):
            raise APIError(422, "validation_error", "Bench view numbers must be finite")
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return value


class BenchViewPatch(_Strict):
    version: Annotated[StrictInt, Field(ge=0)]
    ops: Annotated[list[Op], Field(min_length=1, max_length=MAX_OPS)]
    undo: StrictBool = False

    @model_validator(mode="before")
    @classmethod
    def _finite_input(cls, value: object) -> object:
        return _reject_non_finite(value)


def parse_ops(raw: Sequence[object]) -> list[SetDisplay | UpsertDerived | DeleteDerived]:
    """Validate raw op dicts (for direct callers such as the SOL tools)."""
    _reject_non_finite(list(raw))
    return _OPS.validate_python(list(raw))


# ----------------------------------------------------------------- stored / read


class DisplayEntry(_Strict):
    target: Target
    pinned: StrictBool = False
    hidden: StrictBool = False
    order: Order | None = None
    unit: Unit | None = None
    limits: Limits | None = None
    plot_group: PlotGroup | None = None

    def is_default(self) -> bool:
        return not any(getattr(self, name) for name in DISPLAY_FIELDS) and self.order is None


#: Patchable display fields, in schema order.
DISPLAY_FIELDS: Final = ("pinned", "hidden", "order", "unit", "limits", "plot_group")


class SignalRefOut(_Strict):
    device_id: DeviceId
    signal: SignalName


class DerivedEntry(_Strict):
    id: uuid.UUID
    name: DerivedName
    expression: Annotated[StrictStr, Field(min_length=1, max_length=512)]
    unit: Unit | None = None
    node_count: Annotated[StrictInt, Field(ge=1, le=64)]
    refs: Annotated[list[SignalRefOut], Field(max_length=8)]
    created_at: datetime
    updated_at: datetime


class BenchViewData(_Strict):
    version: Annotated[int, Field(ge=0)]
    display: list[DisplayEntry]
    derived: list[DerivedEntry]
    updated_at: datetime | None


class BenchViewResult(_Strict):
    version: int
    view: BenchViewData
    inverse_ops: list[Op]
