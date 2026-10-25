"""The ONE definition of the search index text (SOLUSDEV-320 T7, docs/api/search.md §1).

`graph_entity.search_text` and `solus_entries.search_text` are `GENERATED ALWAYS … STORED`, so
every write path (ORM, Core insert, bulk update) is covered without app code. The migration,
the ORM `Computed` columns and the dev `create_all` bootstrap all read the SQL strings below;
`entity_search_text` / `entry_search_text` / `flatten_payload` are the Python twins, proven
equal to the SQL by `tests/test_search_text.py`.

Only IMMUTABLE constructs: `||`, `coalesce`, `btrim`, `left` (never `concat_ws`, which is
STABLE), and a recursive plpgsql helper declared IMMUTABLE for the payload flattening. Both
functions pin `search_path` so the recursive call resolves under pg_restore's `search_path = ''`
(it recomputes the STORED columns while COPYing). The text is capped at SEARCH_TEXT_MAX_CHARS:
ingested fields are untrusted and an uncapped ~1 MB value would make the row's own write fail
(`string is too long for tsvector`).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from solus_api.models import GraphEntity, SolusEntry

#: Nesting deeper than this is not indexed (a hardware config bottoms out at depth 5).
MAX_PAYLOAD_DEPTH: Final = 6
#: Characters of index text per row (a six-motor hardware config flattens to ~4k).
SEARCH_TEXT_MAX_CHARS: Final = 32768

_ENTITY_FIELDS: Final = (
    "name",
    "external_ref",
    "attrs->>'path'",
    "attrs->>'manufacturer'",
    "attrs->>'part_number'",
    "attrs->>'mpn'",
    "attrs->>'net'",
    "attrs->>'address'",
    "modality_hints->>'part_number'",
)
ENTITY_SEARCH_SQL: Final = (
    "left(btrim("
    + " || ' ' || ".join(f"coalesce({field}, '')" for field in _ENTITY_FIELDS)
    + f"), {SEARCH_TEXT_MAX_CHARS})"
)
ENTITY_SEARCH_TSV_SQL: Final = f"to_tsvector('simple', {ENTITY_SEARCH_SQL})"
ENTRY_SEARCH_SQL: Final = (
    "left(btrim(coalesce(text, '') || ' ' || coalesce(solus_payload_text(payload), '')), "
    f"{SEARCH_TEXT_MAX_CHARS})"
)
ENTRY_SEARCH_TSV_SQL: Final = f"to_tsvector('simple', {ENTRY_SEARCH_SQL})"

#: `key.path value` pairs separated by spaces; objects prefix keys with dots, arrays use the
#: index as the key segment, nulls render nothing, depth capped at MAX_PAYLOAD_DEPTH.
_PAYLOAD_TEXT_AT_SQL: Final = """
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
    IF depth > __MAX_DEPTH__ THEN
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
""".replace("__MAX_DEPTH__", str(MAX_PAYLOAD_DEPTH))
_PAYLOAD_TEXT_SQL: Final = """
CREATE OR REPLACE FUNCTION solus_payload_text(doc jsonb)
RETURNS text LANGUAGE sql IMMUTABLE STRICT
SET search_path = pg_catalog, public AS $$
    SELECT solus_payload_text_at(doc, '', 0)
$$
"""
#: One statement each (asyncpg prepares one command at a time); run in order.
SOLUS_PAYLOAD_TEXT_STATEMENTS: Final = (_PAYLOAD_TEXT_AT_SQL, _PAYLOAD_TEXT_SQL)
SOLUS_PAYLOAD_TEXT_SQL: Final = ";\n".join(SOLUS_PAYLOAD_TEXT_STATEMENTS) + ";\n"


def _jsonb_text(value: Any) -> str:
    """What `->>` / `#>> '{}'` renders for one JSON value."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, float):
        return format(Decimal(repr(value)), "f")  # jsonb numerics: 1e-7 → 0.0000001, 40.0 → 40.0
    if isinstance(value, int):
        return str(value)
    return json.dumps(value)  # ponytail: nested objects under a scalar key are not search targets


def _jsonb_keys(doc: dict[str, Any]) -> list[str]:
    """jsonb object key order: shorter keys first, then bytewise."""
    return sorted(doc, key=lambda key: (len(key.encode()), key.encode()))


def entity_search_text(entity: GraphEntity) -> str:
    attrs = entity.attrs or {}
    hints = entity.modality_hints or {}
    parts = (
        entity.name,
        entity.external_ref,
        attrs.get("path"),
        attrs.get("manufacturer"),
        attrs.get("part_number"),
        attrs.get("mpn"),
        attrs.get("net"),
        attrs.get("address"),
        hints.get("part_number"),
    )
    return " ".join(_jsonb_text(part) for part in parts).strip(" ")[:SEARCH_TEXT_MAX_CHARS]


def flatten_payload(payload: Any, prefix: str = "", depth: int = 0) -> str:
    """Python twin of `solus_payload_text(jsonb)`."""
    if depth > MAX_PAYLOAD_DEPTH or payload is None:
        return ""
    if isinstance(payload, dict):
        pieces = [
            flatten_payload(payload[key], f"{prefix}.{key}" if prefix else key, depth + 1)
            for key in _jsonb_keys(payload)
        ]
    elif isinstance(payload, list):
        pieces = [
            flatten_payload(item, f"{prefix}.{index}" if prefix else str(index), depth + 1)
            for index, item in enumerate(payload)
        ]
    else:
        text = _jsonb_text(payload)
        return f"{prefix} {text}" if prefix else text
    return " ".join(piece for piece in pieces if piece)


def entry_search_text(entry: SolusEntry) -> str:
    payload = "" if entry.payload is None else flatten_payload(entry.payload)
    return f"{entry.text or ''} {payload}".strip(" ")[:SEARCH_TEXT_MAX_CHARS]
