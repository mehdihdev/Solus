# temp-DECISIONS.md — staged ADR drafts (move into DECISIONS.md on human commit)

> Staging area for ADRs drafted by an AI agent under the founders' explicit instruction, to be
> reviewed and moved into `DECISIONS.md` by a human (only humans edit `DECISIONS.md`). Consistent
> with the provenance rule (CLAUDE.md §5/§10; DECISIONS.md provenance note).

---

## ADR-030: Connector metadata extraction — parse committed Git exports (v1), not live tool plugins

**Status:** Accepted — 2026-07-05, SOLUSDEV-72 (drafted by an AI agent under the founders'
explicit instruction during SOLUS-W0-05; committed by a human). Extends ADR-001 (graph-centric),
underpins the connector interface (SOLUS-W0-05, `docs/contracts/connector-interface.md`), and is
distinct from ADR-014/ADR-029 (Live Bench streaming).
**Context:** Design-artifact connectors — especially EDA (KiCad/LTspice/NgSpice/Altium) and
mechanical CAD (Onshape + proprietary STEP/DWG) — need a source of truth for tool data. Live,
in-tool plugins that stream a running application's state are fragile: they require the tool to be
open, are bespoke per tool, break on tool version changes, and carry no version history. Robotics
teams already commit their exported artifacts to Git — Gerber, STEP, JSON netlists, SPICE decks —
which are versioned, diffable, and available without a live tool session.
**Decision:** v1 connectors extract metadata by **parsing committed Git exports**
(Gerber / STEP / JSON netlist / SPICE), **NOT via live tool plugins**.

- **Native-feed connectors** (code hosts GitHub/GitLab; Onshape) sync via the source's own
  change feed (signature-verified webhooks / API notifications).
- **File-parse connectors** (EDA/CAD) are driven by the **Git repo's change events**: a new commit
  containing the exported artifact fires the connector's re-parse-and-diff path (the diff-based
  change detection in the SOLUS-W0-05 connector interface — `sync` / `detect_changes` +
  `diff_entities`).
- This keeps connectors event-driven (not poll-only), independent (each parses only its own
  source's artifacts and emits intra-source entities/relations), and free of any dependency on a
  running desktop tool. Live tool plugins and live in-tool state are **deferred**.
- **Boundary:** this governs DESIGN-ARTIFACT ingestion into the graph. Live runtime data
  (telemetry, Sim/Real scene state) is NOT a connector concern — it flows through Live Bench's
  `LiveConnection` streaming sibling and the separate telemetry packet-format contract
  (ADR-014/ADR-029). Parsing exports ≠ streaming runtime.

**Rejected:** Live per-tool plugins in v1 (fragile, require the tool running, per-tool engineering
cost, no version history, no clean diff/change-detection story); polling connectors (misses the
real-time-after-a-commit feel and wastes work); treating CAD/EDA the same as live telemetry
(different trust model, different cadence, different contract).
**Revisit when:** a connector genuinely needs live in-tool state that no committed export captures,
or a target tool has no usable committed export format — then a live-plugin or API-pull path is
evaluated behind the same `Connector` interface (the interface does not change; only the extraction
mechanism does).
