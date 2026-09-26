# BOM Store restoration — SOLUSDEV-262 follow-up

Status: implemented, published in the local development environment, and API-verified on
2026-09-14. The remote production service was not deployed or modified.

## Problem and resulting behavior

The active workspace database contained zero catalog extensions, versions or installs. The BOM
implementation existed, but its earlier publication belonged to a separate QA setup. The Store
correctly had no listing to render. The official BOM assets now live inside the API package at
`packages/api/src/solus_api/extensions/bundled/bom/`; both wheel and source distribution include
them. API startup checks that BOM has a live approved listing and intact bundle/Store assets.

An explicitly configured existing staff publisher can reconcile the shipped release through the
normal publication gate and automated review. Repeated setup preserves version identity and
all workspace installations, enablement, settings, grants and account pins. It refuses foreign
ownership, changed immutable bytes, intentional withdrawal, rejected releases and lost/corrupt
storage. Shared environments fail startup on a missing/broken listing; development without a
publisher prints the setup remedy. Setup has a 60-second bound and a cross-process database lock.

The user designated an existing account as the local staff publisher. No password was used or
stored; no synthetic account, account-row promotion or verified badge was created. An ignored
local launcher, `tmp/bom-store-api.sh`, retains the explicitly authorized UUID configuration and
persistent artifact path without credentials. No `.env` was changed.

## Actual local publication evidence

- Listing: `bom`, name `BOM`, publisher `Solus`, version `0.1.0`, review `approved`.
- Version UUID: `01a0a328-c6eb-7eac-8933-b02714038dc0`.
- SHA256: `71e837577c56e40521463ee92120f68c5656ca90e618501f92ec9531e73a9a48`.
- Normal publish and review-completed events emitted; no review problems.
- Startup after publication reconciled the same version; ordinary catalog search returned it.
- Read-only health without staff configuration verified the retained bundle and all Store assets.
- Database after restart: one version, zero project installs (users choose installation).
- The existing BOM is a full-page extension and still requires EDA or CAD. It appears in the
  Store even when those requirements are unmet; hardware alone does not enable Install.

## Validation and reviews

- Integrated existing/new BOM, catalog, installation, publishing, config and startup checks:
  214 passing tests. Separate provisioner suite: 20 passing tests, 91% measured coverage in the
  preceding 19-case run. These counts overlap and should not be summed.
- Setup module: 8 tests passed, 96% coverage; app-factory/lifespan regressions: 6 passed.
- Independent security verification: 26 tests passed; missing/corrupt Store assets and a null
  latest-version pointer were found, fixed and regression-tested.
- Fresh code review approved; independent general/Python review approved after moving resources
  inside the package. Source distribution → wheel build succeeded, all five packaged assets
  exactly matched canonical source bytes. Scoped Ruff and mypy passed.
- No frontend source changed. Automatic approval review rejected opening the local application
  for visual verification, citing the browser-control interface; no alternate browser mechanism
  was used. Store UI verification therefore remains a manual QA item.

## Governing docs and decisions

Read ADR-035 and its first-party amendment, extension architecture, extension API publication /
review / install plans, widget-bundles API plan, Store and BOM wireflows. Tier-1 docs now describe
provisioning and the canonical bundle location. No contract, ADR, AGENTS or hook changes. The
user's unrelated `docs/design/SPEC.md` changes remain untouched. No push or MR was performed.

Production setup uses `SOLUS_FIRST_PARTY_PUBLISHER_ID` and the existing `SOLUS_STAFF_USER_IDS`
authorization, with persistent ArtifactStore configuration. Run `make store-setup` explicitly or
start the API; new environments require the authorized account to exist first. Publishing a new
release does not auto-update installed workspace versions. Intentional withdrawal remains an
operator decision; setup never silently reverses it.

See `COWORK_QA_SOLUSDEV-262-bom-store.md` for independent application acceptance.
