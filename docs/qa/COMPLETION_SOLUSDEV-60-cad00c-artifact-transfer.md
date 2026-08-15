# Completion Report — SOLUS-CAD-00c: bulk artifact transfer over the bridge

**Status:** built, verified, on `SOLUSDEV-60/cad-00c-artifact-transfer`. Ends at the per-ticket gate.

## Why this ticket exists (it was not in the epic)

Phase 0 found that a STEP file **could not cross the bridge at all**. `dispatch.py` dropped every
non-text content block:

```python
NON_TEXT_NOTE = "non-text content omitted (ArtifactRef plumbing pending)"
```

`ArtifactRef` existed as a Pydantic shape and an `artifacts` table, but the byte path was deferred
(`fingerprint/visual.py`: *"ALL ArtifactRef storages are inert…"*), and both the MCP-01 and MCP-03
completion reports flagged *"ArtifactRef upload path for companion bulk data — NOT resolved here."*
Neither workaround was viable: a local file path is useless to a cloud parser, and base64-inlining
a STEP export blows the 1 MiB `tool_result` cap and violates the never-inline rule outright.

So **CAD-02/03/04 had no live path**. This unblocks them.

## What was built

**Companion — `solus_companion/artifacts.py`.** An in-memory staging buffer, not a cache: per
artifact / total-bytes / count budgets, oldest-first eviction (the artifact a fetch wants is the
newest), and `clear()` on disconnect. Nothing touches the filesystem, so a crash leaves nothing
behind on a customer's machine.

**Companion — `dispatch.map_result`.** Non-text content is now staged and the block carries a
handle — `{type, inlined: false, artifact_id, media_type, size_bytes}` — instead of being dropped.
An artifact too large to stage degrades to an honest note rather than failing the call, because the
call itself succeeded. `Dispatcher.handle_artifact_fetch` streams a staged artifact back as chunks.

**Two new frames** (§4 extension rule, **no `protocol_version` bump**):
`artifact_fetch` (cloud → companion) and `artifact_chunk` (companion → cloud).

**Cloud — `bridge/service.fetch_artifact`.** Sends a fetch with a fresh `fetch_id`, reassembles
chunks until `final`. `fetch_id` is a **separate id space** from `call_id`, so a chunk can never
resolve a tool call; unknown ids are dropped and logged (same replay defence as `ingest_result`).

## Bounds — everything the companion sends is untrusted (CLAUDE.md §7)

A pull fails, **never returning a partial artifact**, on any of: total bytes over the limit
(checked *while chunks arrive*, not after reassembly — the mistake the CAD-01 review caught in the
Onshape download), the whole-transfer deadline, malformed base64, an `error` chunk, or session
death. Every failure is a `ToolException`, so callers keep the W0-04 never-raises story.

## Verification

- `ruff check .` clean · `mypy --strict` clean (**122 source files**, api + companion)
- `uv run pytest -q` — **1387 passed, 4 skipped** (was 1364)
- 23 new tests: 11 companion staging · 12 cloud transfer
- **The load-bearing one is the e2e**: `test_bridge_e2e` now drives a real companion against a real
  MCP server over a real socket, calls `mock.pic`, asserts the binary never appears in the
  `tool_result` frame, then pulls `b"BINARYSENTINEL"` back through `fetch_artifact`.

## Delegated-judgment decisions

1. **Pull, not push.** The companion stages and the cloud fetches on demand, matching
   `ArtifactStorage.CLIENT` semantics — the bytes stay on the customer's machine until something
   actually needs them, rather than every binary tool result pushing megabytes uphill.
2. **One `artifact_fetch` → many chunks**, rather than offset-based paging. Fewer round trips, and
   the cloud already owns the deadline.
3. **512 KiB chunks** — comfortably under the 1 MiB frame cap once base64 inflates by 4/3.
4. **An empty artifact still yields one final chunk**, or the cloud would wait for a `final` that
   never comes.
5. **`map_result`'s `store` argument is optional**, so the pre-existing call shape still works and
   degrades to the old note.

## Behaviour change to note at review

`test_companion_dispatch.test_non_text_content_is_never_inlined` was updated: the block now carries
a handle rather than a dropped note. **The invariant it guards is unchanged and still asserted** —
neither the raw bytes nor their base64 appear anywhere in the outbound frame.

## Doc changes

`docs/contracts/bridge-protocol.md` — **Addendum D**: the two frame types, staging and eviction
rules, the separate `fetch_id` space, the bounds, and the disconnect lifecycle.

## Open items

- No connector calls `fetch_artifact` yet — CAD-02 is the first consumer.
- Artifacts are transferred, not yet **persisted** as `artifacts` table rows; `fetch_artifact`
  returns bytes to the caller. Registering a row + S3 offload is a separate concern and not needed
  for the CAD export path, which parses immediately and keeps only the graph.
