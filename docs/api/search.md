# search.md — One index for ⌘K, `@` and SOL (SOLUSDEV-320)

**Last updated:** 2026-10-17. Tier-1 route plan (ADR-032). **Authority:** ADR-003 (Postgres +
pgvector, no second store), ADR-027 (graph conventions), CLAUDE.md §7 (tenant isolation, ingested
text is data). Replaces the ILIKE search of `GET /entities?q=` for the desktop surfaces
(`GET /entities?q=` stays for compatibility; the SOLUSDEV-260 clarification in API.md still holds).

## 1. The index

One migration (`a32000000004`):

- `CREATE EXTENSION IF NOT EXISTS pg_trgm`.
- `graph_entity.search_text TEXT GENERATED ALWAYS AS (…) STORED` from `name`, `external_ref`,
  `attrs.path`, `attrs.manufacturer`, `attrs.part_number`, `attrs.mpn`, `attrs.net`,
  `attrs.address` and `modality_hints.part_number`; `search_tsv tsvector GENERATED ALWAYS AS
  (to_tsvector('simple', <the same expression>)) STORED`; `GIN (search_tsv)` and
  `GIN (name gin_trgm_ops)`. Generated columns cannot be app-maintained wrongly: every write path
  (ORM, Core insert, bulk update) is covered. `graph/search_text.py:entity_search_text(entity)` is
  the Python twin and a parity test proves it equal to the SQL.
- `solus_entries.search_text` = `text` plus a flattened `key.path value` rendering of `payload`
  (`identity.device_ref usb:5B42… protocol.driver_id feetech-sts bus_map.1.model STS3215`) through
  the IMMUTABLE SQL function `solus_payload_text(jsonb)`; generated `search_tsv`; GIN on both.

The text search configuration is `simple` on purpose: MPNs, net names and reference designators
must not be stemmed.

## 2. Service (`services/search.py`)

`search_entities(session, project_id, q, *, kinds=None, domains=None, limit=20)` ranks trigram
similarity on `name` (threshold 0.3) above `ts_rank(search_tsv, plainto_tsquery('simple', q))`,
then an exact `external_ref` match; every row is `{id, kind, domain, name, snippet, score, why}`
with `why ∈ name_match | text_match | ref_match`. `snippet` is the matched text — for `code_file` / `code_module` it is the stored path (`attrs.path`), which the `@` picker shows under the name so two files sharing a name read apart; otherwise the name or the matched `external_ref`. Workspace-domain entities are excluded.
`search_solus(session, project_id, q, *, sections=None, subsections=None, limit=20)` does the same
over `solus_entries` and returns `{id, entity_id, section, subsection, kind, name, snippet, score,
why}`. Both run under the caller's graph read scope. Zero external calls by construction.

## 3. Route

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/search?q=&scope=entities\|solus\|all&kinds=&domains=&sections=&subsections=&limit=` | `q` 1..255 chars; `scope` default `all`; `kinds`/`domains`/`sections`/`subsections` comma lists; `limit` 1..50 per group (default 20) |

Response (`SearchResponse`, a Pydantic model so it reaches `schema.ts`):

```json
{ "data": { "entities": [EntityHit…], "solus": [SolusHit…], "truncated": false } }
```

ProjectCtx (non-member → 404). Reads only. Target: under 100 ms against the copied dev DB.

## 4. Consumers

- ⌘K / Ctrl+K in the shell is the SOLUSDEV-317 command palette (`features/palette/`,
  `docs/wireflows/command-palette.md`). It ranks the OPEN project's loaded entities in memory and,
  for the typed query, calls this route with `scope=all` through `useProjectSearch`: entity hits
  become Nodes (an index hit is a ranking floor for a loaded node, or a new row for one the snapshot
  lacks) and `solus` hits become the `.solus` kind, each opening the entry's own node via
  `entity_id` (an entry without a node yet is skipped). The SOLUSDEV-320 `SearchPalette` it replaced
  was removed at the 2026-10-24 merge.
- The `@` picker (`features/sol/useMentionSearch.ts`) uses `scope=all`; `.solus` hits mention
  through the entry's `entity_id`. A bare `@` (empty query) lists nothing until the first character:
  the route requires `q`.
- SOL (next branch) uses `search_entities` / `search_solus` directly.

Both desktop surfaces share `useProjectSearch` (120 ms debounce, one cache per
`project:scope:q`, stale responses dropped, cache cleared on a graph change hint). A renamed
entity is found by its new name on the next query with no extra event work.

## 5. Error catalogue

| HTTP | `error.code` | Where |
| --- | --- | --- |
| 404 | `not_found` | non-member project |
| 422 | `validation_error` | empty or over-long `q`, unknown scope/section, limit out of range |
