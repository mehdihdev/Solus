"""SOL's three search tools (SOLUSDEV-321 P1-T4): the graph, `.solus` and the practice corpus.

Each is a thin read over a service that already exists, rendered by `bounded_read_tool`:
`search_entities` and `search_solus` (the one index behind ⌘K and `@`, scoped to the project and
leaving out the workspace layer) and `corpus_hits` (the shipped engineering corpus). The project
is bound here, by Solus code, at registration; no argument can name another. A query is held to
255 characters and a limit to 20 whatever the model asks; each search fetches one hit past the
limit so a full page can say more exist (`page_rows`). The corpus is searched by full text
only — embedding the query is a metered model call this read never makes — and an empty corpus
says "corpus not ingested" rather than inventing guidance.
"""

from __future__ import annotations

import uuid
from functools import partial
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import select

from solus_api.agent.tools.read_tool import (
    LIMIT_PARAM,
    QUERY_PARAM,
    ReadResult,
    Row,
    bounded_read_tool,
    limit_arg,
    page_rows,
    query_arg,
)
from solus_api.corpus.retrieval import corpus_hits
from solus_api.corpus.schema import CorpusRelease
from solus_api.services.search import search_entities, search_solus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.agent.tools.registry import ToolRegistry

_PARAMS: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {"q": QUERY_PARAM, "limit": LIMIT_PARAM},
    "required": ["q"],
    "additionalProperties": False,
}


async def search_workspace_handler(
    args: dict[str, Any], *, sessions: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> ReadResult:
    query, limit = query_arg(args), limit_arg(args)
    async with sessions() as session:
        hits = await search_entities(session, project_id, query, limit=limit + 1)
    rows: list[Row] = [
        {
            "name": hit.name,
            "kind": hit.kind,
            "domain": hit.domain,
            "id": hit.id,
            "why": hit.why,
            "score": round(hit.score, 2),
            "snippet": hit.snippet if hit.snippet != hit.name else None,
        }
        for hit in hits
    ]
    return page_rows(rows, limit)


async def search_solus_handler(
    args: dict[str, Any], *, sessions: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> ReadResult:
    query, limit = query_arg(args), limit_arg(args)
    async with sessions() as session:
        hits = await search_solus(session, project_id, query, limit=limit + 1)
    rows: list[Row] = [
        {
            "section": hit.section,
            "subsection": hit.subsection,
            "kind": hit.kind,
            "id": hit.id,
            "entity_id": hit.entity_id,
            "text": hit.name,
            "why": hit.why,
            "score": round(hit.score, 2),
            "snippet": hit.snippet if hit.snippet != hit.name else None,
        }
        for hit in hits
    ]
    return page_rows(rows, limit)


async def search_corpus_handler(
    args: dict[str, Any], *, sessions: async_sessionmaker[AsyncSession]
) -> ReadResult:
    query, limit = query_arg(args), limit_arg(args)
    async with sessions() as session:
        # ponytail: `corpus_hits` holds k to its own MAX_K (20), so at limit 20 the extra hit is
        # never fetched and a full page cannot say more exist; below 20 it can.
        hits = await corpus_hits(session, text=query, k=limit + 1)
        if not hits and await session.scalar(select(CorpusRelease.id).limit(1)) is None:
            return ["corpus not ingested"]
    rows: list[Row] = [
        {
            "id": hit.chunk_id,
            "title": hit.title,
            "domain": hit.domain,
            "topic": hit.topic,
            "kind": hit.kind,
            "confidence": hit.confidence,
            "low_confidence": hit.low_confidence or None,
            "source": hit.attribution,
            "excerpt": hit.chunk.removeprefix(hit.title).lstrip(),
        }
        for hit in hits
    ]
    return page_rows(rows, limit)


def register_search_tools(
    registry: ToolRegistry, sessions: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> None:
    """Add the three search tools, the first two bound to ONE project; the corpus is global."""
    registry.register(
        bounded_read_tool(
            "search_workspace",
            "Search this project's graph entities (parts, nets, code files, robots, CAD parts, "
            "machines) by name, text or exact reference, best match first. Each hit gives its id "
            "(pass it to get_entity to read the entity in full), kind, domain, why it matched "
            "and a snippet.",
            _PARAMS,
            partial(search_workspace_handler, sessions=sessions, project_id=project_id),
        )
    )
    registry.register(
        bounded_read_tool(
            "search_solus",
            "Search this project's .solus entries (goals, constraints, documentation, errors, "
            "environment notes) by text, best match first. Each hit gives its section, id, text "
            "and why it matched.",
            _PARAMS,
            partial(search_solus_handler, sessions=sessions, project_id=project_id),
        )
    )
    registry.register(
        bounded_read_tool(
            "search_corpus",
            "Search Solus's shared engineering practice corpus, reviewed guidance on electrical, "
            "mechanical, software and systems practice. It is general reference, not this "
            "project's data. Each hit gives its id, title, domain, topic, confidence (a low "
            "one is flagged), source and an excerpt. Says so when the corpus is not ingested; "
            "it never invents guidance.",
            _PARAMS,
            partial(search_corpus_handler, sessions=sessions),
        )
    )
