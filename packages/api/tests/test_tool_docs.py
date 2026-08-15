"""The global tool-knowledge store — SOLUS-ONS-A6 / ADR-033.

This is the FIRST global content-bearing table in the schema. Every other table
that stores text is project-scoped by `ForeignKey("projects.id",
ondelete="CASCADE")`, and that FK is what makes cross-tenant leakage structurally
impossible. `tool_doc` has no such anchor, so its containment has to come from
somewhere else — and these tests are that somewhere.

The four rules from ADR-033, each with a test that fails if it erodes:

1. No tenant column and no FK to one. Absence of the column IS the enforcement.
2. Typed columns only — no free-text JSONB a request handler could fill.
3. No runtime write path. Ingestion is an admin job over VENDOR docs.
4. Lexical-first retrieval; `embedding` exists but stays NULL until embed() does.

The counter-example to stay unlike is `DataEvent`: no FKs, but very much
tenant-attributed and content-bearing. "No FK" alone is not containment.
"""

from __future__ import annotations

import pytest
from solus_api.models import ToolDoc
from solus_api.tool_docs import (
    ingest_tool_docs,
    lookup_tool_doc,
    search_tool_docs,
    specs_to_docs,
)
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

# One `featurespecs` message, as `onshape.get_feature_specs` returns it.
_SPEC = {
    "featureType": "extrude",
    "featureTypeName": "Extrude",
    "parameterIdToSpec": {
        "depth": {
            "btType": "BTParameterSpecQuantity-173",
            "parameterId": "depth",
            "parameterName": "Depth",
            "quantityType": "LENGTH",
        },
        "endBound": {
            "btType": "BTParameterSpecEnum-171",
            "parameterId": "endBound",
            "parameterName": "End bound",
            "enumOptions": [{"message": {"value": "BLIND"}}, {"message": {"value": "UP_TO_NEXT"}}],
        },
    },
}


# ------------------------------------------------------- ADR-033 containment


def test_the_table_has_no_tenant_column_at_all() -> None:
    """Rule 1. There must be nowhere to put a tenant reference — not a nullable
    column, not an unenforced uuid. Absence is the enforcement."""
    columns = {c.name for c in inspect(ToolDoc).columns}

    assert "project_id" not in columns
    assert "team_id" not in columns
    assert "user_id" not in columns


def test_the_table_has_no_foreign_keys() -> None:
    """Rule 1, the other half: nothing links this row to a customer."""
    assert not any(column.foreign_keys for column in inspect(ToolDoc).columns)


def test_no_column_is_an_untyped_free_text_bucket() -> None:
    """Rule 2. `parameters` is structured vendor data with a known shape; there
    is no `payload`/`metadata`/`extra` a handler could stuff a prompt into.

    This is what makes `tool_doc` unlike `DataEvent`, which has no FKs but does
    carry an open `payload` and is tenant-attributed.
    """
    columns = {c.name for c in inspect(ToolDoc).columns}

    assert columns.isdisjoint({"payload", "metadata", "extra", "data", "content", "raw"})


def test_every_column_is_one_of_the_declared_ones() -> None:
    """Rule 2, stated positively — the column set is a closed list, so widening
    it is a deliberate act with an ADR behind it rather than a quiet drift."""
    assert {c.name for c in inspect(ToolDoc).columns} == {
        "id",
        "tool",
        "version",
        "symbol",
        "summary",
        "parameters",
        "source_url",
        "confidence",
        "acquisition_method",
        "fetched_at",
        "embedding",
    }


# ------------------------------------------------------------------ ingestion


async def test_specs_become_one_doc_per_feature_type() -> None:
    docs = specs_to_docs("onshape", "v6", [_SPEC], source_url="https://cad.onshape.com/api/openapi")

    assert [d.symbol for d in docs] == ["extrude"]
    assert docs[0].tool == "onshape"
    assert "Extrude" in docs[0].summary


async def test_a_docs_parameters_carry_the_vendor_shape() -> None:
    """The point of the store: "what does extrude take?" is answerable without a
    live call, including each parameter's kind and its enum options."""
    (doc,) = specs_to_docs("onshape", "v6", [_SPEC], source_url="u")

    by_id = {p["id"]: p for p in doc.parameters}
    assert by_id["depth"]["kind"] == "quantity"
    assert by_id["depth"]["quantity_type"] == "LENGTH"
    assert by_id["endBound"]["options"] == ["BLIND", "UP_TO_NEXT"]


async def test_ingestion_records_where_each_entry_came_from() -> None:
    """Attributable, not scraped prose: an entry nobody can trace is an entry
    nobody can re-derive when the vendor changes it."""
    (doc,) = specs_to_docs("onshape", "v6", [_SPEC], source_url="https://example/openapi")

    assert doc.source_url == "https://example/openapi"
    assert doc.acquisition_method == "featurespecs"


async def test_ingesting_twice_updates_rather_than_duplicating(db: AsyncSession) -> None:
    """Vendor docs are regenerated, not appended. A second run of the same job
    must not double every row."""
    await ingest_tool_docs(db, specs_to_docs("onshape", "v6", [_SPEC], source_url="u"))
    await ingest_tool_docs(db, specs_to_docs("onshape", "v6", [_SPEC], source_url="u2"))

    rows = (await db.scalars(select(ToolDoc))).all()
    assert len(rows) == 1
    assert rows[0].source_url == "u2"


async def test_the_embedding_stays_null(db: AsyncSession) -> None:
    """Rule 4. The column exists so adding vectors later is a backfill, not a
    migration — but `embed()` does not exist, so nothing may pretend it does."""
    await ingest_tool_docs(db, specs_to_docs("onshape", "v6", [_SPEC], source_url="u"))

    row = (await db.scalars(select(ToolDoc))).one()
    assert row.embedding is None


# ------------------------------------------------------------------ retrieval


async def test_an_exact_lookup_finds_the_entry(db: AsyncSession) -> None:
    """Rule 4: "what does extrude take?" is a lookup, not a semantic search."""
    await ingest_tool_docs(db, specs_to_docs("onshape", "v6", [_SPEC], source_url="u"))

    doc = await lookup_tool_doc(db, tool="onshape", version="v6", symbol="extrude")

    assert doc is not None
    assert doc.symbol == "extrude"


async def test_a_lookup_for_another_tool_finds_nothing(db: AsyncSession) -> None:
    await ingest_tool_docs(db, specs_to_docs("onshape", "v6", [_SPEC], source_url="u"))

    assert await lookup_tool_doc(db, tool="fusion", version="v6", symbol="extrude") is None


async def test_search_falls_back_to_text_when_the_symbol_is_not_exact(
    db: AsyncSession,
) -> None:
    await ingest_tool_docs(db, specs_to_docs("onshape", "v6", [_SPEC], source_url="u"))

    found = await search_tool_docs(db, tool="onshape", query="extru")

    assert [d.symbol for d in found] == ["extrude"]


async def test_search_is_bounded(db: AsyncSession) -> None:
    """An unbounded query over a global table is a query every tenant shares."""
    many = [
        specs_to_docs("onshape", "v6", [{**_SPEC, "featureType": f"f{i}"}], source_url="u")[0]
        for i in range(40)
    ]
    await ingest_tool_docs(db, many)

    assert len(await search_tool_docs(db, tool="onshape", query="f", limit=5)) == 5


async def test_search_cannot_be_asked_for_an_unbounded_page(db: AsyncSession) -> None:
    with pytest.raises(ValueError):
        await search_tool_docs(db, tool="onshape", query="x", limit=10_000)


async def test_a_query_with_sql_wildcards_is_treated_as_literal_text(
    db: AsyncSession,
) -> None:
    """`%` and `_` are LIKE metacharacters. Unescaped, `%` matches everything —
    turning a narrow lookup into a full-table read."""
    await ingest_tool_docs(db, specs_to_docs("onshape", "v6", [_SPEC], source_url="u"))

    assert await search_tool_docs(db, tool="onshape", query="%") == []


# --------------------------------------------------- rule 3: no tenant reaches it


def test_no_function_here_accepts_a_tenant_argument() -> None:
    """Rule 3, made mechanical.

    The table is safe to be global only because customer data has no route in.
    If someone ever adds `project_id` to an ingestion signature, this fails —
    which is the moment to ask what customer data was about to be written to a
    table every tenant reads.
    """
    import inspect as py_inspect

    forbidden = {"project_id", "team_id", "user_id", "project", "team", "user", "context", "ctx"}
    for function in (specs_to_docs, ingest_tool_docs, lookup_tool_doc, search_tool_docs):
        assert forbidden.isdisjoint(py_inspect.signature(function).parameters)


def test_ingestion_is_not_reachable_from_any_router() -> None:
    """There is no runtime write path: no request handler imports the writer.

    A customer's own `featurespecs` includes custom features THEY imported —
    customer data. Those are read live through `onshape.get_feature_specs` and
    never stored here, which only holds if no request can reach the writer.
    """
    import pathlib

    routers = pathlib.Path(__file__).resolve().parents[1] / "src" / "solus_api" / "routers"
    offenders = [
        path.name
        for path in routers.glob("*.py")
        if "ingest_tool_docs" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
