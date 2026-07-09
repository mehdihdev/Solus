# Completion Report — SOLUS-W0-05: Connector Interface Contract

**Branch:** `SOLUSDEV-72-shared-dev-models` (Week-0 contracts). **Status:** complete,
integrated, validation-green, left uncommitted for human review → MR.

---

## What was built

The interface every design-artifact connector implements (code hosts, mechanical CAD, EDA) —
a human-owned Week-0 contract (ADR-028) and the blocking dependency for API Phase 3.

**`packages/api/src/solus_api/connectors/`:**

- `base.py` — `Integration(abc.ABC)` (connect/disconnect) → `Connector` (sync/detect_changes +
  the inherited `diff_entities` helper); `Session` (`@dataclass` base); the normalized shapes
  `ConnectorConfig` / `EntityOut` / `RelationOut` / `SyncResult` / `Delta`; and `read_secret`
  (the stubbed AWS Secrets Manager seam).
- `conformance.py` — `assert_connector_conforms`, the reusable **connector contract suite**
  every connector must pass (credential hygiene, `connect`→`Session`, well-formed unique
  entities, the intra-source-relations invariant, `Delta` keyed by `source_id`, `disconnect`
  must not raise).
- `__init__.py` — re-exports.

**`docs/contracts/connector-interface.md`** — the contract (class hierarchy, the Secrets
Manager seam, `source_id` as the linchpin == `graph_entity.external_ref` == fingerprint
`SourceRef.external_ref`, `modality_hints` as the bridge to W0-06, intra-source-only relations,
the two change-detection patterns + diff helper, event-driven sync, a Security section, and the
`LiveConnection` documented sibling).

**`tests/test_connector_contract.py`** — a reference `FakeConnector` that passes the suite, a
`_BadConnector` proving the suite catches cross-source relations + duplicate `source_id`s, and
unit tests for the diff helper, the `read_secret` stub, and credential hygiene.

## Governing docs consulted

CLAUDE.md §1 (one common connector interface → graph entities+relations, SDK-extractable) + §7
(credentials & untrusted-ingest), ADR-001 (graph-centric), ADR-027 + `models.py` provenance
(`source_connector`/`external_ref`, `graph_edge.domain_pair`), ADR-028 (human-owned), ADR-014/029
(Live Bench — the `LiveConnection` sibling and its separate telemetry packet-format contract),
`docs/api/API.md §2.5` (the sources/sync/webhook surface this interface satisfies).

## Test coverage

10 connector tests; full suite **170 passed**; mypy strict clean (43 files); ruff clean.
Acceptance proven: FakeConnector passes conformance; `diff_entities` buckets added/changed/removed
by `source_id`; the suite catches cross-source relations, duplicate `source_id`s, a credential in
`options`, and a non-denylisted credential field; `read_secret` is a stub with no fallback;
`ConnectorConfig` has no plaintext credential channel; the suite refuses to run under `-O`.

## Decisions under delegated judgment

1. **ABC, not Protocol (the repo's first).** The repo uses `typing.Protocol` everywhere, but this
   design needs a nominal hierarchy with INHERITED implementation (shared parent, the inherited
   `diff_entities`, the `LiveConnection` sibling) — a structural Protocol can't provide that. The
   ticket mandates ABC; it is the correct tool here.
2. **Secrets Manager via a stubbed `read_secret`, no boto3** (wired in a later infra ticket). The
   only credential channel; `ConnectorConfig` carries a `secret_ref`, never a plaintext secret.
3. **`Delta` v1 = entity deltas only** (`added/changed/removed`); relation changes reconcile via a
   full `sync()`; relation deltas are a documented forward extension (ticket "if needed"; YAGNI).
4. **`Session` is a non-frozen `@dataclass`** (a live handle holding a mutable client), a
   deliberate deviation from the frozen-DTO idiom.
5. **The conformance suite ships in the package** so the ~9 connectors' tests can import it (it IS
   the "connector contract suite," CLAUDE.md §6); `FakeConnector` is a test double.

## Phase-4 review outcomes (3 parallel reviewers) — all findings fixed before handoff

- **Security HIGH (fixed)** — the credential-hygiene check was bypassable (only exact-name field
  scan; `options` dict unscanned). Now a substring scan over field names AND `options` keys
  (catches `client_secret`, `private_key`, `options={"token":…}`). +2 tests.
- **Code HIGH (fixed)** — `domain_pair` format diverged from the locked convention
  (`graph_edge.domain_pair` is lowercase `Domain` values joined by `<->`, e.g.
  `electrical<->electrical`, not `ELECTRICAL↔ELECTRICAL`). Aligned in `base.py`, the doc, and the
  fixtures — important since this is the reference for ~9 authors.
- **Python HIGH (fixed)** — the assert-based suite ships in the package → asserts compile out under
  `python -O`, silently passing. Added a `if not __debug__: raise RuntimeError(...)` guard.
- **Code LOW (fixed)** — "disconnect must not raise" is now enforced (wrapped → `AssertionError`),
  not just commented.
- **Security/Python LOW+MEDIUM (fixed)** — `read_secret` docstring reinforced (never log/return
  creds); frozen-is-shallow / not-hashable caveats added to `EntityOut`; denylist drift removed
  (single source of truth); the doc's credential-enforcement claim corrected to be honest
  (structural enforcement + the ABC limitation, below).
- **Confirmed clean:** ABC design, `diff_entities` correctness, typing under mypy strict, async
  correctness, intra-source invariant, no injection/SQL/`shell=True`/secret literals.

## Flagged for the founders

1. **⚠ Unrecorded architectural decision → recommend ADR-030.** The "v1 = parse committed Git
   exports (Gerber/STEP/netlist/SPICE), NOT live tool plugins" strategy the ticket is built around
   is not in any ADR or doc — it lives only in the ticket. It should be ratified as a human-authored
   ADR so the contract can cite it durably. (Flagged in the doc header.)
2. **First ABC in the repo** (vs the pervasive `Protocol` idiom) — justified by inherited
   implementation; called out in `base.py` and the doc.
3. **`integrations/CLAUDE.md` (planned in the repo tree) does not exist yet** — connector rules
   currently live in root CLAUDE.md only.
4. **ABC limitation (security MEDIUM, by design):** the conformance suite enforces credential
   hygiene _structurally_ (no plaintext field/options), but an interface contract cannot observe how
   a connector internally sources creds inside `connect()`. That "only via `read_secret`" rule is
   upheld by the seam being the sole channel + CI secret-scanning + review — documented honestly in
   §2/§10 rather than over-claimed.

## Out of scope (documented, not built)

The 9 real connectors, `LiveConnection` streaming, the webhook receiver / event queue /
sync-on-change plumbing, and the ingestion pipeline consuming `SyncResult`/`Delta`.

## Human handoff steps

Review the branch + this report; decide ADR-030; `git add`/commit/push, open the MR, merge after
review; run the Cowork QA pass on the connector contract when connectors land.
