# §2.20 Engineering corpus (`/api/v1/corpus`) — CORPUS C2 (SOLUSDEV-241)

> **Tier-1 amendment** (ADR-032): docs/api had no corpus plan; this file was added with the
> implementation and is called out in the completion report. Authority: ADR-036,
> `docs/corpus/SCOPE.md`, `docs/corpus/LICENSING.md`, `docs/schemas/corpus-chunk.md`.

The corpus is **global and tenant-free by design**: every authenticated user reads the same
shipped chunks, and the tenancy boundary is what a row _cannot contain_ (no customer identifier,
no free-form container, reviewer-signed prose), not who may read it. There is **no write route**:
the only write path is the deploy/admin step `python -m solus_api.corpus ingest` (ADR-036 rule 3).
Only `status = active` chunks are ever served; `draft` is invisible over HTTP and to SOL.

Auth on every route: authenticated user (`CurrentUser`). No team or project context is taken —
there is nothing to scope. Standard envelope `{ "data": … }`; errors are the §1.3 shape.

## GET /api/v1/corpus/manifest

What corpus the API is serving (schema §8 — the version the desktop, the API and SOL agree on).

`200`:

```json
{
  "data": {
    "corpus_version": "0.1.0",
    "released_at": "2026-09-06",
    "policy_revision": "docs/corpus/LICENSING.md@43e8a06",
    "applied_at": "2026-09-06T14:02:11Z",
    "chunk_count": 58,
    "manifest_hash": "sha256:…"
  }
}
```

`404 corpus_not_ingested` — no release has been applied to this database.

## GET /api/v1/corpus/search

Query: `q` (1–500 chars, required), `domain` (repeatable, `mechanical|electrical|software|systems|robotics`),
`topic` (repeatable, a `SCOPE.md` §4 topic value), `limit` (1–20, default 5).

Filters are WHERE clauses (a `domain` filter can never return another domain's chunk); an unknown
`domain`/`topic` value yields an empty list, never a widened search. Ranking over HTTP is English
full-text only (CLAUDE.md §7 cost control: the unmetered embed seam serves admission-capped SOL
turns, never an arbitrary request); SOL's own corpus pull uses ANN when a key is configured.
Scores are comparable within one response only.

`200`:

```json
{
  "data": [
    {
      "id": "corpus:electrical/decoupling/loop-area",
      "title": "Decoupling capacitor placement is about loop area, not distance",
      "domain": "electrical",
      "topic": "decoupling",
      "kind": "principle",
      "audience": "fundamentals",
      "score": 0.83,
      "confidence": 0.9,
      "low_confidence": false,
      "excerpt": "A decoupling capacitor supplies the transient current an IC draws…"
    }
  ]
}
```

## GET /api/v1/corpus/chunks/{chunk_id}

`chunk_id` is the full id, e.g. `corpus:electrical/decoupling/loop-area` (path-encoded as given —
the id contains `:` and `/`). Resolves a citation SOL made: Guide mode renders the attribution
and further reading; Expert mode the id and the value.

`200` — the served view of a chunk. `reviewer`, `reviewed_at`, `drafting`, `content_hash` and
`embedding` are deliberately absent (schema §6: never in a prompt, never over the wire).

```json
{
  "data": {
    "id": "corpus:electrical/decoupling/loop-area",
    "domain": "electrical",
    "topic": "decoupling",
    "title": "…",
    "body": "…",
    "kind": "principle",
    "audience": "fundamentals",
    "status": "active",
    "confidence": 0.9,
    "confidence_basis": "vendor_stated",
    "applicability": [{ "key": "fabrication_class", "value": "prototype" }],
    "source": {
      "class": "solus_authored",
      "title": "Solus engineering corpus",
      "publisher": "Solus",
      "url": null,
      "license": "solus-proprietary",
      "attribution": ""
    },
    "further_reading": [
      { "title": "…", "author": "…", "identifier": "…", "url": null }
    ],
    "related": ["corpus:electrical/pcb_layout_basics/return-paths"],
    "supersedes": null,
    "corpus_version": "0.1.0",
    "revised_in": "0.1.0"
  }
}
```

A `withdrawn` chunk resolves with `status: "withdrawn"` and an empty `body` so past citations
still land somewhere honest. `404 chunk_not_found` — unknown id **or a draft** (drafts do not
exist over HTTP).

## Not in this plan

- Any write, review, or activation route. Review happens in the content tree at the MR
  (LICENSING.md §6); activation is a content change plus an ingest.
- Per-user or per-team corpus customisation. Preferences select and rank (`SCOPE.md` §6);
  they never add text.
