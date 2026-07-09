# Hand-off: promote the connector interface to `packages/contracts/python/`

Decision B unified the connector interface **in place** in `solus_api.connectors` (green +
tested now). This directory stages the extracted contract package for you to place into the
human-owned contract home `packages/contracts/python/` (H1-blocked for agents, per ADR-028).
Agents can't write there — you do. Delete this `temp-contracts-python/` dir after placing.

## What's here

- `pyproject.toml` — the `solus-contracts` package metadata.
- `solus_contracts/__init__.py` — re-exports the interface from `solus_contracts.connector`.
- **`solus_contracts/connector.py` is deliberately NOT shipped here.** Duplicating the 180-line
  interface would (a) drift from the canonical source and (b) trip the H6 no-recreation guard.
  Instead, copy the canonical module verbatim when you place the package (step 1 below):
  `cp packages/api/src/solus_api/connectors/contracts.py .../solus_contracts/connector.py`,
  then adjust only the `Domain` import per the decision below. The current `contracts.py`
  already contains the grafted `modality_hints` field and the ratified shape.

## RESOLVE FIRST — the `Domain` coupling (one real decision)

`connector.py` references the `Domain` enum, which ADR-027 says is owned by
`solus_api/models.py`. A standalone contract package **must not depend on `solus_api`** (that
would invert the dependency: api → contracts → api). Pick one before wiring:

- **(A, recommended) Relocate `Domain` into the contract package.** Move the `Domain` enum into
  `solus_contracts` (e.g. `solus_contracts/graph.py`), have `solus_api/models.py` import it back
  from there, and `connector.py` import it locally. Cleanest long-term seam; touches ADR-027 +
  `models.py` (both-founder sign-off).
- **(B) Keep the canonical impl in `solus_api.connectors`** and treat `packages/contracts/python/`
  as a published _mirror_ that documents the shape (no runtime import from it yet). Smallest
  footprint; the in-place unification remains the source of truth until (A) is done.

Until you choose, the shipped code is fully functional: `solus_api.connectors` is the canonical
import surface and all tests pass. This package is the _relocation_, not a correctness gate.

## Wiring steps (after choosing above)

1. `mkdir -p packages/contracts/python && cp -r temp-contracts-python/* packages/contracts/python/`
   then copy the canonical interface in:
   `cp packages/api/src/solus_api/connectors/contracts.py packages/contracts/python/solus_contracts/connector.py`
   and adjust its `Domain` import per the decision above. (Drop this README or keep it as the
   package README.)
2. Root `pyproject.toml` → add to the uv workspace:
   ```toml
   [tool.uv.workspace]
   members = ["packages/api", "packages/contracts/python"]
   ```
3. `packages/api/pyproject.toml` → add the dependency + path source:
   ```toml
   dependencies = [ ..., "solus-contracts" ]
   [tool.uv.sources]
   solus-contracts = { workspace = true }
   ```
4. Flip `packages/api/src/solus_api/connectors/contracts.py` to re-export from the package:
   `from solus_contracts.connector import *  # noqa: F403` (or explicit re-exports), so
   `solus_api.connectors` keeps working unchanged.
5. `uv sync --all-packages`, then `cd packages/api && uv run pytest -q` to confirm green.

## Paste-in companions

- `temp-connector-interface-decisionB.md` → amend `docs/contracts/connector-interface.md`.
- `temp-ADR-connector-interface.md` → add the ADR to `DECISIONS.md`.
