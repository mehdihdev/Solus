# Development credits

Authority: ADR-024 development exception, explicitly approved 2026-09-12.
The existing pre-flight → routing → provider → accounting sequence in
`docs/contracts/model-orchestration.md` remains in place. A server-owned Settings
allowlist is attached to database sessions; credit/trial admission checks consult
one predicate before their ordinary balance/spend checks. Exact `app_env=dev`
and membership are both required. Missing configuration fails closed. No ledger
mutation, fake grant, authentication, rate, loop, or tool approval bypass is added.

The credits and usage APIs expose only the current user's effective boolean and
real accounting figures, never the allowlist. `pnpm dev:all` may load UUIDs from
a gitignored `.solus-dev-credits.json` in this checkout, through a JSON-only
validated reader. An explicit environment allowlist takes precedence. Production
still disables the exception even if the setting is accidentally present.
