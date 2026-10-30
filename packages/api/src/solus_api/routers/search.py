"""`GET /projects/{id}/search` — one index for ⌘K, `@` and SOL (SOLUSDEV-320 T7;
docs/api/search.md §3). Reads only; non-member → 404 through `ProjectCtx`."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from solus_api.core.errors import APIError
from solus_api.deps import ProjectCtx, SessionDep
from solus_api.models import Domain, SolusSection
from solus_api.routers.entities import _csv
from solus_api.services.search import MAX_LIMIT, SearchResponse, search_entities, search_solus

router = APIRouter(prefix="/api/v1/projects/{project_id}")

Scope = Literal["entities", "solus", "all"]


class SearchEnvelope(BaseModel):
    data: SearchResponse


@router.get("/search", response_model=SearchEnvelope)
async def search_project(
    ctx: ProjectCtx,
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=255)],
    scope: Annotated[Scope, Query()] = "all",
    kinds: Annotated[str | None, Query(max_length=1024)] = None,
    domains: Annotated[str | None, Query(max_length=256)] = None,
    sections: Annotated[str | None, Query(max_length=256)] = None,
    subsections: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 20,
) -> SearchEnvelope:
    try:
        domain_values = [Domain(d) for d in _csv(domains) or []]
        section_values = [SolusSection(s) for s in _csv(sections) or []]
    except ValueError as exc:
        raise APIError(422, "validation_error", str(exc)) from exc
    project_id = ctx.project.id
    response = SearchResponse()
    # limit + 1 so `truncated` is honest without a count query; the extra row is dropped.
    if scope != "solus":
        hits = await search_entities(
            session, project_id, q, kinds=_csv(kinds), domains=domain_values, limit=limit + 1
        )
        response.entities = hits[:limit]
        response.truncated |= len(hits) > limit
    if scope != "entities":
        entries = await search_solus(
            session,
            project_id,
            q,
            sections=section_values,
            subsections=_csv(subsections),
            limit=limit + 1,
        )
        response.solus = entries[:limit]
        response.truncated |= len(entries) > limit
    return SearchEnvelope(data=response)
