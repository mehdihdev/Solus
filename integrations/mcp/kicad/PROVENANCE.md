# Provenance — `kicad`

> Filled from `integrations/mcp/PROVENANCE.template.md` (MCP-03, SOLUSDEV-100 T1a).
> An unfilled field, or a stale vendored-tree hash, voids the sign-offs below.

## Identity

- **Server name:** `kicad` — equals `MCPServerSpec.name` and this directory's name
  (`^[a-z][a-z0-9_]{0,31}$`).
- **Spec location:** `packages/api/src/solus_api/agent/tools/mcp_servers.py::KICAD` — the one
  spec that binds to this fork.

## Upstream

- **Repository:** `https://github.com/lamaalrajih/kicad-mcp` — the canonical upstream, not a
  mirror.
- **Commit SHA:** `98c9ea41cb393393a8bafd157a93e84431e00afb` — the exact commit vendored
  (upstream merge commit "Merge pull request #33 from paul356/workaround_null_ctx").
- **Tag / version:** `none` — upstream publishes no release tags; its `pyproject.toml` declares
  version `0.1.0`.
- **Fork date:** `2026-08-03` — when `upstream/` was imported at that SHA.
- **Vendored tree hash:** `56f30452214d88aa6b84807d6df7a6e903c48e52` — recompute with
  `git rev-parse HEAD:integrations/mcp/kicad/upstream`. Any change to `upstream/` changes this
  hash and mechanically voids the sign-offs (proposed CI recomputes and fails on mismatch;
  `tests/test_launch_entrypoint.py` recomputes it on every test run today).

## License

- **SPDX:** `MIT` — verified against `upstream/LICENSE` ("MIT License, Copyright (c) 2025 Lama
  Al Rajih") before import.
- **LICENSE file:** `upstream/LICENSE` — retained verbatim, never edited.
- **NOTICE (Apache-2.0 only):** n/a (MIT).
- **Copyright:** original headers retained in all `upstream/` files; Solus headers only on files
  under `solus/` and `bin/`.

## Local modifications

One row per deviation from a verbatim import of the pinned SHA (files under `solus/` and `bin/`
are Solus-authored and need no rows). The import is byte-identical to upstream at the pinned SHA
**except** the exclusions below (human-approved F6 exclusion pattern: `CLAUDE.md`, `.claude/`,
`agents/`, `.mcp.json`, `.github/`). Of those patterns, only `.github/` existed upstream at the
pinned SHA; `.git/` is never vendored by definition.

| Date       | File(s)                                                | What & why                                                                                                                                                                                                                                                                                                                                               | Author                    |
| ---------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| 2026-08-03 | `.github/` (5 files: CI workflow, issue/PR templates)  | Not vendored — upstream repo automation/templates, never imported at runtime; F6 exclusion pattern approved for SOLUSDEV-100.                                                                                                                                                                                                                            | SOLUSDEV-100 T1a agent    |
| 2026-08-03 | `upstream/pyproject.toml` (`[tool.ruff]` section only) | Appended a Solus-marked ruff exclusion block (`force-exclude = true`, `extend-exclude = ["**"]`). Ruff resolves the NEAREST config per file, so this vendored pyproject — not the repo root — governs `upstream/`; without the block the H8/H10 quality hooks lint reviewed third-party code. No runtime behavior change (packaging/lint metadata only). | SOLUSDEV-100 orchestrator |

Install-time note (not an `upstream/` edit): `bin/launch` execs the fork-private interpreter
`integrations/mcp/kicad/.venv/bin/python3`. That virtualenv is NOT committed — the companion
install/update step materializes it from `requirements.lock.txt` with hash verification
(`--require-hashes` semantics; BRG follow-up). `bin/launch` itself performs zero network I/O
and no installs.

## Exposed tools

- **Allowlist:** `./allowlist.yaml` — authoritative; per-tool `requires_confirmation` lives
  THERE. Completed by T1b (2026-08-03); the whole file is human-ratified at the MR. The
  `ServerAllowlist` model forbids extra fields, so the exposed/total ratio is recorded HERE,
  not in the yaml.
- **Exposed / upstream total:** `5 / 16` — upstream's seven register modules define 16 tools;
  the overlay registers 5 of them verbatim (`list_projects`, `get_project_structure`,
  `extract_project_netlist`, `analyze_schematic_connections`, `analyze_bom`) plus 1
  Solus-authored tool (`export_netlist`, `solus/netlist_export.py`) — 6 registered total.
  Enforcement is fork-side, not just cloud-side: `bin/launch` execs `solus/server.py`
  (T1b, replacing `upstream/main.py`) and `solus/registration.py` drives upstream's register
  functions through a trimming shim, so the 11 unexposed upstream tools (`open_project`,
  `validate_project`, `extract_schematic_netlist`, `find_component_connections`,
  `export_bom_csv`, `get_drc_history_tool`, `run_drc_check`, `generate_pcb_thumbnail`,
  `generate_project_thumbnail`, `identify_circuit_patterns`,
  `analyze_project_circuit_patterns`) and ALL upstream resources/prompts are never registered —
  dead in-process (`tests/test_overlay_tool_trimming.py`).
- **Draft-name mapping (spec draft → upstream reality):** `list_projects` → `list_projects`;
  `get_project_summary` → `get_project_structure`; `extract_netlist` →
  `extract_project_netlist`; `get_schematic_summary` → `analyze_schematic_connections`;
  `analyze_bom` → `analyze_bom`; `export_netlist` → Solus-authored (upstream has no single-shot
  netlist file-export tool).
- **Destructive tools:** one allowlisted — `set_symbol_property`
  (`requires_confirmation: true`; mutates a design file on the customer machine). Drafted NOW so
  no later MR widens an existing allowlist (integrations/mcp/CLAUDE.md rule 2); its
  implementation lands in T2b and it is NOT registered until then (test-pinned). Upstream's
  own kicad-cli-invoking tools (DRC, exports, thumbnails) are not exposed at all.
- **Solus overlay shims** (T1a flags a–c + T1b findings d–e; all in `solus/`, zero `upstream/`
  bytes changed — the vendored tree hash is unaffected; full evidence in `SECURITY_REVIEW.md`
  §7):

  | Row | Flag                                                        | Shim                                                                                                                                     |
  | --- | ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
  | a   | upstream `main.py` opens `kicad-mcp.log` inside `upstream/` | `solus/server.py` entry: stderr-only logging, `sys.dont_write_bytecode`; nothing ever writes inside `upstream/`                          |
  | b   | `utils/env.py::load_dotenv` logs env VALUES from a `.env`   | unreachable: only `main.py` calls it and the entry never imports it; env arrives solely via the launcher's scrubbed allowlist            |
  | c   | child PATH posture / CLI probing of common install paths    | `solus/cli_detect.py`: `KICAD_CLI_PATH` or pinned `PATH=/usr/bin:/bin` only, detected once; absent CLI → `degraded: true`, stable reason |
  | d   | upstream tool bodies `print()` onto the stdio protocol      | registered wrappers divert tool stdout to stderr (`solus/trimming.py`)                                                                   |
  | e   | `ctx` params could surface as model-suppliable inputs       | wrappers strip `ctx` from the visible signature and pass `ctx=None` (upstream's null-ctx path)                                           |

- **Env-allowlist declaration relocated (T1a follow-up):** the written declaration now lives in
  `solus/env_allowlist.py`; `bin/launch` and `tests/test_launch_entrypoint.py` are pinned to it.
  The declared set itself is UNCHANGED (same 11 names).

## Vendored library tree — `vendor/` (`circuit-synth/kicad-sch-api`, T2a)

The fork's SECOND vendored tree (human-ratified two-tree layout, F7): a pure schematic-file
library the Solus overlay (T2b) builds its write path on. It sits OUTSIDE `upstream/`, so the
upstream tree hash above is unaffected.

- **Repository:** `https://github.com/circuit-synth/kicad-sch-api` — the canonical upstream, not
  a mirror.
- **Commit SHA:** `505bca23e91cf3fa6e3b66976e529e775eada3ba` — the exact commit vendored
  (upstream `pyproject.toml` declares version `0.5.6`).
- **Fork date:** `2026-08-03`.
- **SPDX:** `MIT` — verified against `vendor/LICENSE` ("MIT License, Copyright (c) 2025
  Circuit-Synth") before import; the LICENSE file is retained verbatim at `vendor/LICENSE`.
- **Vendor tree hash:** `844e1a1183e90a0a3b0c89dbcffe561b6fc9b944` — recompute with
  `git rev-parse HEAD:integrations/mcp/kicad/vendor` (any change to `vendor/` changes this hash
  and mechanically voids the sign-offs; `tests/test_vendor_sch_api.py` recomputes it on every
  test run via the scratch-index method).
- **Layout:** the repo root maps to `vendor/` and only the library subset is retained, so the
  importable package is `vendor/kicad_sch_api/` — `import kicad_sch_api` works with `vendor/`
  on `sys.path` (how `solus/` consumes it). Retained verbatim: `LICENSE`, `README.md`,
  `CHANGELOG.md`, `pyproject.toml`, `uv.lock`, and `kicad_sch_api/` minus the strips below.

### Exclusions and strips (one row per deviation from a verbatim import)

| Date       | Path(s)                                                                                                                                                                                                                     | What & why                                                                                                                                                                                                                                                                                                                                                                                                                  | Author                    |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| 2026-08-03 | `.github/`, `CLAUDE.md`, `.claude/`, `agents/`, `.mcp.json`                                                                                                                                                                 | Not vendored — F6 exclusion pattern approved for SOLUSDEV-100; all five exist at the pinned SHA. `.git/` is never vendored by definition.                                                                                                                                                                                                                                                                                   | SOLUSDEV-100 T2a agent    |
| 2026-08-03 | `mcp_server/`                                                                                                                                                                                                               | Not vendored — upstream's bundled MCP server subpackage. The fork must not gain a second MCP server (`bin/launch` execs `solus/server.py` only). Removes every `mcp`/`fastmcp`/`pydantic` import site. Its console entry points (`kicad-sch-mcp`, etc.) remain DECLARED in the verbatim `vendor/pyproject.toml` but are inert: the vendored tree is never pip-installed — the overlay imports it from `sys.path`.           | SOLUSDEV-100 T2a agent    |
| 2026-08-03 | `kicad_sch_api/exporters/`, `kicad_sch_api/cli/kicad_to_python.py`                                                                                                                                                          | Not vendored — the Python-code-generation feature, the only modules importing `jinja2` (and optionally `black`); `cli/kicad_to_python.py` imports the excluded exporter at module top. Consequence: `Schematic.export_to_python()` raises `ImportError` if called (it imports the exporter lazily); nothing else in the retained tree references it. This strips the `jinja2` dependency without editing any vendored file. | SOLUSDEV-100 T2a agent    |
| 2026-08-03 | `docs/`, `examples/`, `scripts/`, `tests/`, `CONTRIBUTING.md`, `KNOWN_ISSUES.md`, `MANIFEST.in`, `pytest.ini`, dotfiles (`.gitignore`, `.gitleaks.toml`, `.pre-commit-config.yaml`, `.pypirc.example`, `.readthedocs.yaml`) | Not vendored — upstream development/documentation material, never imported at runtime; the vendored subset is the pure library the overlay ships to customer machines, keeping the two-dev review surface (ADR-031) proportionate. `tests/mcp/` and `tests/integration/test_pin_discovery_workflow.py` also import the excluded `mcp_server`.                                                                               | SOLUSDEV-100 T2a agent    |
| 2026-08-03 | `kicad_sch_api/cli.py` (top-level module)                                                                                                                                                                                   | Removed post-vendor — dead upstream vestige: the `cli/` PACKAGE shadows it, so it is unimportable at runtime; keeping both makes mypy refuse the tree as a duplicate module (`kicad_sch_api.cli`) under the explicit-path H8/H10 hook runs.                                                                                                                                                                                 | SOLUSDEV-100 orchestrator |

### Dependency truth

The retained modules' ONLY third-party import root is `sexpdata` (verified by AST scan,
`tests/test_vendor_sch_api.py`). `vendor/pyproject.toml` — kept verbatim — still DECLARES
`pydantic`, `mcp`, `fastmcp`, `jinja2` (and `typing-extensions` for Python < 3.11): those serve
only the excluded `mcp_server/` and `exporters/` code paths and the recorded fact here replaces
an in-tree edit. `sexpdata==1.0.2` is pinned with hashes in `requirements.lock.txt` (pin + hashes
verbatim from `vendor/uv.lock`).

- **ACCEPTED LICENSE EXCEPTION:** `sexpdata` is `BSD-2-Clause`. ADR-031's fork boundary says
  MIT/Apache-2.0 only; vendoring/shipping this BSD-2-Clause _dependency_ was human-approved
  in-session on 2026-08-03 (SOLUSDEV-100). A wording clarification to ADR-031 (permissive
  non-copyleft deps of a fork vs. the fork itself) is proposed separately — this row is the
  written record until that lands.

### Sign-off

This tree ships under the fork's shared gate: the **Security review sign-off** section below
covers BOTH vendored trees — reviewers pin the upstream tree hash AND the vendor tree hash
above. Blank until both devs sign.

## Update / rebase policy

- **CVE intake:** GitHub Security Advisories + Dependabot alerts on Solus-owned watch forks of
  `lamaalrajih/kicad-mcp` AND `circuit-synth/kicad-sch-api` (both vendored trees), plus the CI
  dependency-audit job (CLAUDE.md §7) run against `requirements.lock.txt` on every pipeline.
- **Cadence:** quarterly upstream diff review; a CVE affecting a shipped code path → re-vendor
  within **14 days**.
- **Rebase procedure:** re-import `upstream/` at the new SHA as a fresh verbatim commit (same
  exclusion rows re-evaluated), replay Solus-authored changes, update SHA + tree hash above,
  regenerate `requirements.lock.txt` from the new upstream lock, re-run the security checklist
  (scoped re-review rules in `SECURITY_REVIEW.template.md` §8). Step-by-step in `./README.md`.

## Security review sign-off

Both lines required before the fork ships, and again after any re-review trigger
("reviewed by both devs" — no self-approval, no single-reviewer shipping).

- **Reviewer 1:** `<name>` — `<date>` — tree hash reviewed: `<SHA>` — checklist:
  `SECURITY_REVIEW.md §<date>`
- **Reviewer 2:** `<name>` — `<date>` — tree hash reviewed: `<SHA>` — checklist:
  `SECURITY_REVIEW.md §<date>`

## Re-review triggers (any of these voids the sign-offs above)

- Any change to `upstream/` or `vendor/` (rebase, backport, in-tree edit) — the two tree hashes
  make this mechanical.
- Any allowlist **addition**, or any `requires_confirmation` flip **true→false**. (Removals and
  false→true shrink surface: one reviewer suffices.)
- Any change to `bin/launch`, the declared env allowlist inside it (also pinned by
  `tests/test_launch_entrypoint.py`), or the declared sandbox posture.
- Any dependency added or version-changed in the lockfile.
- A published CVE in any dependency at a version the lockfile pins.
- For url-transport specs bound to this record: any endpoint URL change.
