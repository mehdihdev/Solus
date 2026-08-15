# COWORK QA — LB-06 Telemetry Packet Format (SOLUSDEV-126)

> **Read this first.** LB-06 is a **wire format and codec**, not a screen. It introduces **no user
> flow, no UI, and no API route** — nothing in the running application changes visibly, and there
> is deliberately nothing to click. `Live Bench` still shows its honest empty state, because the
> transport that would carry these packets (LB-01 sim / LB-02 robot / CON-03 Foxglove) is not
> built yet.
>
> So this file is a **developer-level verification plan**, not a click-through. Everything below
> runs from a terminal in a checkout. Anyone who was expecting a UI pass should stop here and mark
> the whole file N/A — that is the correct outcome, not a failure.

## Setup

- [ ] A checkout of the branch, `uv` and `pnpm` installed.
- [ ] `make db-up` (Postgres + Redis via docker-compose). Needed only for Flow 4 (full suite);
      Flows 1–3 and 5 need no database and no services.
- [ ] No accounts, no connected sources, no sample data required.
- [ ] Commands below assume repo root unless stated. If `uv` warns
      `VIRTUAL_ENV=... does not match the project environment path`, prefix commands with
      `unset VIRTUAL_ENV &&` — that is a stale env var from another checkout, not a fault.

---

## Flow 1 — The format round-trips (core behaviour)

1. `cd packages/api && uv run pytest tests/test_packet.py tests/test_codec.py -q`
   - [ ] **Expected:** all pass (~39 tests), no failures, no errors.
2. Encode and decode a packet by hand:
   ```
   cd packages/api && uv run python -c "
   from datetime import UTC, datetime
   from solus_api.graph.codec import encode, decode, encode_json
   from solus_api.graph.packet import TelemetryPacket
   p = TelemetryPacket(device_id='imu0', timestamp=datetime.now(UTC), seq=7,
                       values={'rpm': 1200.5}, units={'rpm': 'rev/min'})
   print(encode_json(p)); print(decode(encode(p)) == p)
   "
   ```
   - [ ] **Expected:** a one-line JSON object containing `device_id`, `schema_version`, `seq`,
         `ts_us`, `units`, `values` — then `True`.
   - [ ] **Expected:** `ts_us` is a large integer (microseconds), **not** a date string.

## Flow 2 — Versioning safety (the load-bearing property)

The whole point of the format: a decoder must read a packet from a **newer** producer.

3. `cd packages/api && uv run pytest tests/test_codec.py -q -k "newer or unknown_fields"`
   - [ ] **Expected:** passes. An old decoder reads a packet carrying `schema_version: 2` plus
         fields it has never heard of, ignores the surplus, and reports the higher version rather
         than rewriting it to 1.
4. Confirm the strict/tolerant split by hand:
   ```
   cd packages/api && uv run python -c "
   from solus_api.graph.codec import from_wire, to_wire
   from solus_api.graph.packet import TelemetryPacket
   from datetime import UTC, datetime
   p = TelemetryPacket(device_id='d', timestamp=datetime.now(UTC), values={'x':1.0})
   print('tolerant decode:', from_wire(to_wire(p) | {'invented_later': 'ok'}) == p)
   try:
       TelemetryPacket.model_validate({**p.model_dump(), 'invented_later': 'ok'}); print('BUG')
   except Exception: print('strict construction: rejected as expected')
   "
   ```
   - [ ] **Expected:** `tolerant decode: True` **and** `strict construction: rejected as expected`.
         Both halves matter — tolerance lives in the decoder, never in the model.

## Flow 3 — The two runtimes agree (drift gate)

5. `npx vitest related --run apps/desktop/src/renderer/src/lib/telemetry/packet.ts`
   - [ ] **Expected:** 32 tests pass. (Use this command, **not** `pnpm test --silent <file>` — hook
         H9's `--silent` form is incompatible with vitest 3 and errors out; that is a known harness
         gap, not a test failure.)
6. Prove the gate actually bites. Edit `packages/api/src/solus_api/graph/packet.py` and change
   `SCHEMA_VERSION = 1` to `2`, then:
   - `cd packages/api && uv run pytest tests/test_telemetry_corpus.py -q`
   - [ ] **Expected: FAILS**, naming the stale fixtures and printing the regeneration command.
7. Regenerate and re-check: `cd packages/api && uv run python tests/telemetry_corpus.py`
   - `uv run pytest tests/test_telemetry_corpus.py -q` → [ ] **Expected:** passes again.
   - `npx vitest related --run apps/desktop/src/renderer/src/lib/telemetry/packet.ts`
   - [ ] **Expected: FAILS** on the `limits.json` assertion — TypeScript now disagrees with Python.
8. **Revert both changes** (`git checkout -- packages/api/src/solus_api/graph/packet.py` and
   re-run the generator) and confirm both suites are green again.
   - [ ] **Expected:** green Python, green TypeScript, `git status` clean.

> Steps 6–7 are the point of the whole mechanism: neither runtime can change the format alone.

## Flow 4 — Nothing else broke

9. `cd packages/api && uv run pytest -q` (needs `make db-up`; takes ~5 minutes)
   - [ ] **Expected:** 1230 passed, 3 skipped. Baseline before this work was 1196 passed, 3 skipped.
10. `make lint` and `make typecheck`
    - [ ] **Expected:** ruff "All checks passed", mypy "Success: no issues found", eslint **0
          errors** (pre-existing `max-lines-per-function` warnings in unrelated files are expected).

## Flow 5 — Hostile input (security boundary)

Decoding is a trust boundary: these bytes come from a device nobody controls.

11. `cd packages/api && uv run pytest tests/test_codec.py -q -k "reject or oversized or malformed or truncated or empty"`
    - [ ] **Expected:** all pass.
12. Spot-check that a bad packet raises **one** error type and never crashes the process:
    ```
    cd packages/api && uv run python -c "
    from solus_api.graph.codec import decode, decode_json, PacketDecodeError
    for label, fn, payload in [('truncated', decode, b'\x82\xa9dev'),
                               ('oversized', decode, b'\x00'*70000),
                               ('empty', decode, b''),
                               ('bad json', decode_json, '{nope')]:
        try: fn(payload); print('BUG: accepted', label)
        except PacketDecodeError: print('rejected:', label)
    "
    ```
    - [ ] **Expected:** four `rejected:` lines, no traceback, no `BUG:`.

## Edge cases / failure paths

- [ ] **Naive timestamp rejected** — a packet without timezone info must not validate.
- [ ] **NaN / Infinity rejected** — msgpack can carry them; the boundary must refuse them so they
      never reach a chart axis or a window mean.
- [ ] **Units naming an absent signal rejected** — producer/packet disagreement is an error.
- [ ] **`seq` absent decodes as `None`, not `0`** — an unsequenced stream must be distinguishable
      from one whose first packet is number zero.
- [ ] **`ts_us` in TypeScript is exact; `timestamp` is truncated.** A JS `Date` holds only
      milliseconds. Re-encoding a packet in the UI must use `ts_us`; if `timestamp` were used,
      `…123456µs` would silently become `…123000µs`.

## Cross-feature interactions to verify

- [ ] **LNK-06 graph plumbing unaffected** — `uv run pytest tests/test_telemetry.py tests/test_buffer.py tests/test_resolver.py -q` passes. The added packet fields are all defaulted, so existing producers keep working.
- [ ] **MCP-02 Pattern 2 intact** — `uv run pytest tests/test_live_connection.py -q` passes. Telemetry must not have grown an MCP tool surface.
- [ ] **No API surface added** — `grep -rn "telemetry" packages/api/src/solus_api/routers/` returns nothing. LB-06 deliberately adds no route.
- [ ] **Live Bench unchanged** — `pnpm dev:api` + `pnpm dev:desktop`, open Live Bench: still the
      honest empty state. Nothing streams, because no transport exists yet. **This is correct.**

## Known gaps (do not raise as bugs)

- `units` is carried on the packet but **not** stored in the recent-values buffer; propagating it
  to `RecentValuesView` is LB-05/LNK-06 follow-up.
- `seq` is specified here but nothing yet **uses** it for drop/reorder detection — that is LB-02's
  edge observers.
- There is no ingest transport or HTTP route; the format is exercised at the module boundary only.
