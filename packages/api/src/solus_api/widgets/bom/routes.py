"""The BOM widget's routes (SOLUSDEV-246 ST4, widget-bundles.md §11).

Mounted by `routers/widgets.py` at `/api/v1/projects/{project_id}/widgets/bom`
under `require_bundle("bom")`: installed + enabled + unblocked or 404, member
floor and the install-write budget on every write — no handler carries auth.
"""

from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal, get_args

from fastapi import APIRouter, Depends, Path, Response
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from solus_api.agent.tools.tool import ToolException
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import SessionDep
from solus_api.services.events import emit_event
from solus_api.widgets.bom import service
from solus_api.widgets.bom.rows import (
    COST_MAX,
    ITEM_CATEGORIES,
    LIFECYCLE_STATES,
    NAME_MAX,
    NOTES_MAX,
    QUANTITY_MAX,
    SLUG,
    TEXT_MAX,
    BomRow,
    is_row_key,
    render_csv,
    totals,
)
from solus_api.widgets.guard import BundleContext, require_bundle

router = APIRouter()
Bom = Annotated[BundleContext, Depends(require_bundle(SLUG))]


def _no_control_characters(allow_newlines: bool) -> Callable[[str], str]:
    """Reject every Unicode "Other" code point (controls, format characters such
    as bidi overrides, surrogates, unassigned) — security review L4. Notes may
    keep newlines and tabs."""
    allowed = {"\n", "\t", "\r"} if allow_newlines else set()

    def check(value: str) -> str:
        for ch in value:
            if ch not in allowed and unicodedata.category(ch).startswith("C"):
                raise ValueError("control characters are not allowed")
        return value

    return check


_ONE_LINE = AfterValidator(_no_control_characters(allow_newlines=False))
_MULTI_LINE = AfterValidator(_no_control_characters(allow_newlines=True))
Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX), _ONE_LINE
]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=TEXT_MAX), _ONE_LINE]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=NOTES_MAX), _MULTI_LINE]
PartNumber = Annotated[str, StringConstraints(strip_whitespace=True, max_length=64), _ONE_LINE]
Quantity = Annotated[int, Field(ge=1, le=QUANTITY_MAX)]
Cost = Annotated[float, Field(ge=0, le=COST_MAX)]
State = Literal["planned", "ordered", "received", "installed", "retired"]
Category = Literal["raw_material", "purchase"]
if set(get_args(State)) != set(LIFECYCLE_STATES) or set(get_args(Category)) != set(
    ITEM_CATEGORIES
):  # pragma: no cover — contract pin, checked at import
    raise ValueError("BOM route literals drifted from rows.py")


class ItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Name
    category: Category
    quantity: Quantity = 1
    state: State = "planned"
    part_number: PartNumber | None = None
    manufacturer: Short | None = None
    supplier: Short | None = None
    unit_cost: Cost | None = None
    notes: Notes | None = None


class PatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Name | None = None
    quantity: Quantity | None = None
    state: State | None = None
    supplier: Short | None = None
    unit_cost: Cost | None = None
    notes: Notes | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> PatchBody:
        if not self.model_dump(exclude_unset=True):
            raise ValueError("nothing to change")
        return self


def _row_key(key: str = Path()) -> str:
    if not is_row_key(key):
        raise APIError(422, "validation_error", "Invalid BOM row key")
    return key


RowKey = Annotated[str, Depends(_row_key)]


def _payload(
    rows: list[BomRow], inputs: service.BomInputs, config: service.BomConfig
) -> dict[str, Any]:
    return {
        "slug": SLUG,
        "rows": [r.payload() for r in rows],
        "totals": totals(rows, config.cost_target),
        "config": config.payload(),
        "states": list(LIFECYCLE_STATES),
        "truncated": inputs.truncated,
    }


async def _view(
    bundle: Bom, session: SessionDep
) -> tuple[list[BomRow], service.BomInputs, service.BomConfig]:
    project_id = bundle.ctx.project.id
    inputs = await service.load_inputs(session, project_id)
    config = await service.load_config(session, project_id, bundle.manifest)
    return inputs.rows(), inputs, config


def _find(rows: list[BomRow], key: str) -> BomRow:
    row = next((r for r in rows if r.key == key), None)
    if row is None:
        raise APIError(404, "not_found", "No such BOM row")
    return row


def _emit(bundle: Bom, session: SessionDep, event_type: str, payload: dict[str, Any]) -> None:
    emit_event(
        session,
        user=bundle.ctx.user,
        event_type=event_type,
        team_id=bundle.ctx.team.id,
        project_id=bundle.ctx.project.id,
        payload=payload,
    )


@router.get("/rows")
async def list_rows(bundle: Bom, session: SessionDep) -> dict[str, Any]:
    rows, inputs, config = await _view(bundle, session)
    return envelope(_payload(rows, inputs, config))


def _item_row(entity: Any) -> BomRow:
    """An item's own row, without rebuilding the whole view (security review M5)."""
    item = service.item_from_entity(entity)
    if item is None:  # pragma: no cover — we just wrote a valid item
        raise APIError(500, "internal_error", "BOM row is malformed")
    return service.row_for_item(item)


@router.post("/rows", status_code=201)
async def create_row(body: ItemBody, bundle: Bom, session: SessionDep) -> dict[str, Any]:
    fields = body.model_dump(exclude={"name", "category"}, exclude_none=True)
    try:
        item = await service.create_item(
            session,
            project_id=bundle.ctx.project.id,
            user_id=bundle.ctx.user.id,
            name=body.name,
            category=body.category,
            fields=fields,
            manifest=bundle.manifest,
        )
    except ToolException as exc:
        raise APIError(422, "validation_error", exc.message) from exc
    _emit(bundle, session, "bom.item_added", {"category": body.category, "item_id": str(item.id)})
    await session.commit()
    await session.refresh(item)
    return envelope(_item_row(item).payload())


@router.patch("/rows/{key}")
async def patch_row(
    key: RowKey, body: PatchBody, bundle: Bom, session: SessionDep
) -> dict[str, Any]:
    patch = body.model_dump(exclude_unset=True)
    project_id = bundle.ctx.project.id
    if key.startswith("item:"):
        item = await service.find_item(session, project_id, uuid.UUID(key.split(":", 1)[1]))
        if item is None:
            raise APIError(404, "not_found", "No such BOM row")
        service.apply_patch(item, patch)
        kind = str(item.attrs.get("category"))
        _emit(bundle, session, "bom.row_updated", {"row_kind": kind, "fields": sorted(patch)})
        await session.commit()
        await session.refresh(item)
        return envelope(_item_row(item).payload())
    if "quantity" in patch or "name" in patch:
        raise APIError(
            422, "validation_error", "A design row's name and quantity come from the design"
        )
    rows, _, _ = await _view(bundle, session)
    row = _find(rows, key)
    try:
        await service.upsert_overlay(
            session,
            project_id=project_id,
            user_id=bundle.ctx.user.id,
            row=row,
            patch=patch,
            manifest=bundle.manifest,
        )
    except ToolException as exc:
        raise APIError(422, "validation_error", exc.message) from exc
    _emit(bundle, session, "bom.row_updated", {"row_kind": row.kind, "fields": sorted(patch)})
    await session.commit()
    rows, _, _ = await _view(bundle, session)
    return envelope(_find(rows, key).payload())


@router.delete("/rows/{key}", status_code=204, response_model=None)
async def delete_row(key: RowKey, bundle: Bom, session: SessionDep) -> None:
    project_id = bundle.ctx.project.id
    if key.startswith("item:"):
        target = await service.find_item(session, project_id, uuid.UUID(key.split(":", 1)[1]))
    else:
        target = await service.find_overlay(session, project_id, key)
    if target is None:
        raise APIError(404, "not_found", "No such BOM row")
    service.soft_delete(target)
    _emit(bundle, session, "bom.item_removed", {"row_key_kind": key.split(":", 1)[0]})
    await session.commit()


@router.get("/export.csv", response_model=None)
async def export_csv(bundle: Bom, session: SessionDep) -> Response:
    rows, _, _ = await _view(bundle, session)
    _emit(bundle, session, "bom.exported", {"rows": len(rows)})
    await session.commit()
    filename = f"bom-{bundle.ctx.project.id}.csv"
    return Response(
        content=render_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["router"]
