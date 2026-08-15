"""Ingestion and retrieval for the tool-knowledge store — SOLUS-ONS-A6 / ADR-033.

**This module is the ONLY write path to `tool_docs`, and it is an admin/ingestion
job — never a request handler.** Nothing here takes a `SyncContext`, a
`GraphEntity`, a project, or a user; there is no argument through which customer
data could arrive. That is rule 3 of ADR-033, and it is why the table can safely
be global.

What goes in is **vendor documentation**, from machine-readable sources: Onshape's
public OpenAPI spec and its per-document `featurespecs` (which is the authority on
what a part studio can actually accept, custom features included). A hand-written
schema table is the thing that rots; entries here are regenerable from their
source and carry the url they came from.

Retrieval is lexical-first because "what does extrude take?" is a lookup, not a
semantic search: exact `tool`+`version`+`symbol`, then a bounded text search.
`ToolDoc.embedding` exists so vectors are a later backfill rather than a
migration, and stays NULL until `embed()` does.

Note the deliberate contrast with `connectors/onshape_ops.py`: that module turns a
spec into an executable BTM parameter for a WRITE; this one turns the same spec
into prose a model can read. Same source, opposite direction, no shared code.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import ToolDoc, utcnow

logger = logging.getLogger("solus.tool_docs")

#: A global table serves every tenant, so an unbounded query is everyone's
#: problem. Callers may ask for less, never more.
MAX_SEARCH_LIMIT: Final = 50
DEFAULT_SEARCH_LIMIT: Final = 10

#: `BTParameterSpec…-nnn` → the plain kind a model can reason about. Unknown
#: spec types map to "other" rather than being dropped: knowing a parameter
#: EXISTS is useful even when its kind is not one we have a word for.
_SPEC_KINDS: Final[dict[str, str]] = {
    "BTParameterSpecQuantity": "quantity",
    "BTParameterSpecNullableQuantity": "quantity",
    "BTParameterSpecEnum": "enum",
    "BTParameterSpecMultiEnum": "enum",
    "BTParameterSpecBoolean": "boolean",
    "BTParameterSpecString": "string",
    "BTParameterSpecQuery": "geometry",
    "BTParameterSpecFeatureList": "feature_list",
}

_SUMMARY_CAP: Final = 1024
_SYMBOL_CAP: Final = 128


def _kind(bt_type: Any) -> str:
    """The parameter kind, from the spec's own btType prefix."""
    base = str(bt_type or "").split("-")[0]
    return _SPEC_KINDS.get(base, "other")


def _options(spec: dict[str, Any]) -> list[str]:
    """Enum members, unwrapped from Onshape's `{btType, message}` envelope."""
    raw = spec.get("enumOptions")
    values: list[str] = []
    for option in raw if isinstance(raw, list) else []:
        if not isinstance(option, dict):
            continue
        message = option.get("message")
        source = message if isinstance(message, dict) else option
        value = source.get("value")
        if isinstance(value, str):
            values.append(value)
    return values


def _documented_parameter(parameter_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    """One parameter, described rather than executed.

    Distinct from `onshape_ops._parameter`, which builds an executable BTM
    payload from the same input — this side never touches a value.
    """
    entry: dict[str, Any] = {
        "id": parameter_id,
        "name": str(spec.get("parameterName") or parameter_id),
        "kind": _kind(spec.get("btType")),
    }
    quantity_type = spec.get("quantityType")
    if isinstance(quantity_type, str):
        entry["quantity_type"] = quantity_type
    options = _options(spec)
    if options:
        entry["options"] = options
    return entry


def specs_to_docs(
    tool: str,
    version: str,
    specs: Iterable[dict[str, Any]],
    *,
    source_url: str,
    acquisition_method: str = "featurespecs",
) -> list[ToolDoc]:
    """Turn `featurespecs` messages into documentation rows.

    Pure — no session, no I/O — so the mapping is testable on its own and the
    write path stays a single, obvious function.
    """
    docs: list[ToolDoc] = []
    for spec in specs:
        feature_type = spec.get("featureType")
        if not isinstance(feature_type, str) or not feature_type:
            continue
        by_id = spec.get("parameterIdToSpec")
        parameters = [
            _documented_parameter(parameter_id, parameter_spec)
            for parameter_id, parameter_spec in (by_id if isinstance(by_id, dict) else {}).items()
            if isinstance(parameter_spec, dict)
        ]
        display = spec.get("featureTypeName") or feature_type
        docs.append(
            ToolDoc(
                tool=tool,
                version=version,
                symbol=feature_type[:_SYMBOL_CAP],
                summary=f"{display} ({feature_type}): {len(parameters)} parameters."[:_SUMMARY_CAP],
                parameters=parameters,
                source_url=source_url,
                # Machine-readable and versioned; nothing here is inferred.
                confidence=1.0,
                acquisition_method=acquisition_method,
                fetched_at=utcnow(),
            )
        )
    return docs


async def ingest_tool_docs(session: AsyncSession, docs: Sequence[ToolDoc]) -> int:
    """Upsert vendor documentation. Returns how many rows were written.

    Vendor docs are REGENERATED rather than appended, so re-running the job must
    refresh rows in place instead of doubling them — hence the upsert on the
    (tool, version, symbol) identity.
    """
    if not docs:
        return 0
    values = [
        {
            "tool": doc.tool,
            "version": doc.version,
            "symbol": doc.symbol,
            "summary": doc.summary,
            "parameters": doc.parameters,
            "source_url": doc.source_url,
            "confidence": doc.confidence,
            "acquisition_method": doc.acquisition_method,
            "fetched_at": doc.fetched_at,
        }
        for doc in docs
    ]
    statement = insert(ToolDoc).values(values)
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_tool_docs_identity",
            set_={
                key: getattr(statement.excluded, key)
                for key in (
                    "summary",
                    "parameters",
                    "source_url",
                    "confidence",
                    "acquisition_method",
                    "fetched_at",
                )
            },
        )
    )
    await session.flush()
    logger.info("ingested %d tool docs for %s", len(values), docs[0].tool)
    return len(values)


async def lookup_tool_doc(
    session: AsyncSession, *, tool: str, version: str, symbol: str
) -> ToolDoc | None:
    """Exact lookup — the common case, and the cheap one."""
    doc: ToolDoc | None = await session.scalar(
        select(ToolDoc).where(
            ToolDoc.tool == tool, ToolDoc.version == version, ToolDoc.symbol == symbol
        )
    )
    return doc


def _literal(query: str) -> str:
    """Escape LIKE metacharacters.

    Unescaped, a bare `%` matches every row — turning a narrow lookup into a
    full read of a table every tenant shares.
    """
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search_tool_docs(
    session: AsyncSession,
    *,
    tool: str,
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> list[ToolDoc]:
    """Bounded text fallback for when the caller does not know the exact symbol."""
    if limit < 1 or limit > MAX_SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}")
    pattern = f"%{_literal(query)}%"
    rows = await session.scalars(
        select(ToolDoc)
        .where(
            ToolDoc.tool == tool,
            ToolDoc.symbol.ilike(pattern, escape="\\")
            | ToolDoc.summary.ilike(pattern, escape="\\"),
        )
        .order_by(ToolDoc.symbol)
        .limit(limit)
    )
    return list(rows.all())


__all__ = [
    "DEFAULT_SEARCH_LIMIT",
    "MAX_SEARCH_LIMIT",
    "ingest_tool_docs",
    "lookup_tool_doc",
    "search_tool_docs",
    "specs_to_docs",
]
