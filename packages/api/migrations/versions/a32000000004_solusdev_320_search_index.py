"""SOLUSDEV-320: one search index for ⌘K, `@` and SOL (docs/api/search.md §1).

Revision ID: a32000000004
Revises: a32000000003

`pg_trgm`, the IMMUTABLE `solus_payload_text(jsonb)` flattener, generated `search_text` /
`search_tsv` on `graph_entity` and `solus_entries`, and the four GIN indexes (built
CONCURRENTLY in an autocommit block, after the column adds commit). Also rewrites the legacy
`graph_edge.origin = 'recognition'` rows (the SOLUSDEV-73 recognition router that wrote them is
gone; `system` is their EdgeOrigin) and refuses any origin outside the vocabulary.

Everything below is a FROZEN copy of `solus_api.graph.search_text` and
`solus_contracts.relations.EdgeOrigin` as of this revision, so the revision replays the same
way on every database; `tests/test_search_index_migration.py` fails the moment the live
definitions drift, which means: write a new migration, never edit this one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision: str = "a32000000004"
down_revision: str | None = "a32000000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENTITY_TEXT = (
    "left(btrim(coalesce(name, '') || ' ' || coalesce(external_ref, '') || ' ' || "
    "coalesce(attrs->>'path', '') || ' ' || coalesce(attrs->>'manufacturer', '') || ' ' || "
    "coalesce(attrs->>'part_number', '') || ' ' || coalesce(attrs->>'mpn', '') || ' ' || "
    "coalesce(attrs->>'net', '') || ' ' || coalesce(attrs->>'address', '') || ' ' || "
    "coalesce(modality_hints->>'part_number', '')), 32768)"
)
_ENTRY_TEXT = (
    "left(btrim(coalesce(text, '') || ' ' || coalesce(solus_payload_text(payload), '')), 32768)"
)
FROZEN_COLUMNS = (
    ("graph_entity", _ENTITY_TEXT, f"to_tsvector('simple', {_ENTITY_TEXT})"),
    ("solus_entries", _ENTRY_TEXT, f"to_tsvector('simple', {_ENTRY_TEXT})"),
)
FROZEN_PAYLOAD_TEXT_STATEMENTS = (
    """
CREATE OR REPLACE FUNCTION solus_payload_text_at(doc jsonb, prefix text, depth int)
RETURNS text LANGUAGE plpgsql IMMUTABLE STRICT
SET search_path = pg_catalog, public AS $$
DECLARE
    acc text := '';
    piece text;
    k text;
    v jsonb;
    i int := 0;
BEGIN
    IF depth > 6 THEN
        RETURN '';
    END IF;
    CASE jsonb_typeof(doc)
        WHEN 'object' THEN
            FOR k, v IN SELECT key, value FROM jsonb_each(doc) LOOP
                piece := solus_payload_text_at(
                    v, CASE WHEN prefix = '' THEN k ELSE prefix || '.' || k END, depth + 1);
                IF piece <> '' THEN
                    acc := CASE WHEN acc = '' THEN piece ELSE acc || ' ' || piece END;
                END IF;
            END LOOP;
        WHEN 'array' THEN
            FOR v IN SELECT value FROM jsonb_array_elements(doc) LOOP
                piece := solus_payload_text_at(
                    v, CASE WHEN prefix = '' THEN i::text ELSE prefix || '.' || i END, depth + 1);
                IF piece <> '' THEN
                    acc := CASE WHEN acc = '' THEN piece ELSE acc || ' ' || piece END;
                END IF;
                i := i + 1;
            END LOOP;
        WHEN 'null' THEN
            RETURN '';
        ELSE
            RETURN CASE WHEN prefix = '' THEN doc #>> '{}'
                        ELSE prefix || ' ' || (doc #>> '{}') END;
    END CASE;
    RETURN acc;
END
$$
""",
    """
CREATE OR REPLACE FUNCTION solus_payload_text(doc jsonb)
RETURNS text LANGUAGE sql IMMUTABLE STRICT
SET search_path = pg_catalog, public AS $$
    SELECT solus_payload_text_at(doc, '', 0)
$$
""",
)
FROZEN_ORIGINS = ("connector", "manual", "inferred", "fingerprint", "system")
_INDEXES = (
    ("ix_graph_entity_search_tsv", "graph_entity", "search_tsv", None),
    ("ix_graph_entity_name_trgm", "graph_entity", "name", "gin_trgm_ops"),
    ("ix_solus_entries_search_tsv", "solus_entries", "search_tsv", None),
    ("ix_solus_entries_search_text_trgm", "solus_entries", "search_text", "gin_trgm_ops"),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for statement in FROZEN_PAYLOAD_TEXT_STATEMENTS:
        op.execute(statement)
    for table, text_sql, tsv_sql in FROZEN_COLUMNS:
        op.add_column(
            table, sa.Column("search_text", sa.Text(), sa.Computed(text_sql, persisted=True))
        )
        op.add_column(
            table, sa.Column("search_tsv", TSVECTOR(), sa.Computed(tsv_sql, persisted=True))
        )
    # CONCURRENTLY cannot run inside a transaction: the column adds commit first, then each
    # index builds without blocking graph writes. IF NOT EXISTS makes a retry after a failed
    # concurrent build (which leaves an INVALID index) idempotent after `DROP INDEX`.
    with op.get_context().autocommit_block():
        for name, table, column, ops in _INDEXES:
            op.create_index(
                name,
                table,
                [column],
                postgresql_using="gin",
                postgresql_ops={column: ops} if ops else {},
                postgresql_concurrently=True,
                if_not_exists=True,
            )
    bind = op.get_bind()
    # Data step, not reversible: 'recognition' rows cannot be told apart afterwards.
    bind.execute(sa.text("UPDATE graph_edge SET origin = 'system' WHERE origin = 'recognition'"))
    for table, _, _ in FROZEN_COLUMNS:
        missing = bind.scalar(sa.text(f"SELECT count(*) FROM {table} WHERE search_text IS NULL"))  # noqa: S608 — table names are this module's constants
        if missing:
            raise RuntimeError(f"{missing} {table} rows have no search_text")
    stray = bind.scalar(
        sa.text("SELECT count(*) FROM graph_edge WHERE origin NOT IN :origins").bindparams(
            sa.bindparam("origins", list(FROZEN_ORIGINS), expanding=True)
        )
    )
    if stray:
        raise RuntimeError(f"{stray} graph_edge rows carry an origin outside EdgeOrigin")


def downgrade() -> None:
    # The 'recognition' → 'system' origin rewrite is not undone (as a32000000001): the old
    # value carried no information worth restoring and the rows are no longer distinguishable.
    for name, table, _, _ in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
    for table, _, _ in FROZEN_COLUMNS:
        op.drop_column(table, "search_tsv")
        op.drop_column(table, "search_text")
    op.execute("DROP FUNCTION IF EXISTS solus_payload_text(jsonb)")
    op.execute("DROP FUNCTION IF EXISTS solus_payload_text_at(jsonb, text, int)")
    # The extension stays: other sessions may already depend on it.
