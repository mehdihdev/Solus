# CLAUDE.md — apps/desktop (Solus renderer)

Extends the root CLAUDE.md. Within this directory these rules add detail; they never relax root security or testing requirements.

## What this app is

The Solus desktop client: Electron + React 19 + TypeScript (strict) + Vite + Tailwind v4 + Zustand + React Router (hash history). The renderer is the user-facing surface; `main`/`preload` stay thin. Stack is locked by ADR-008.

## Layout (renderer `src/renderer/src/`)

```
theme/        design tokens (tokens.constants.ts) + applyTheme — runtime CSS-var theming
components/ui/ design-system primitives (Button, Card, Mono, Spinner, Segmented, Field, Wordmark, SolOrb, icons)
lib/          supabase client (env-driven), api/ typed REST client + envelope types
store/        Zustand stores (authStore, settingsStore) — persisted via localStorage
features/<area>/ feature panels, each owning its components + a *Store + *.constants + tests
routes/       AppRoutes + auth/onboarding guards
```

Organize by feature, not by type. Many small files (root coding-style rule). Feature panels are scoped to their directory.

## Conventions

- **Design tokens, not hardcoded colors.** Use the CSS vars (`var(--bg)`, `var(--acc)`, `var(--mut)`, domain colors `--sw/--ee/--me/--rt`) or the Tailwind utilities mapped to them (`bg-bg`, `text-mut`, `font-mono`). `theme/applyTheme.ts` sets the vars at runtime; switching theme re-skins everything. New colors go in `tokens.constants.ts`.
- **Typed API client only.** All REST goes through `lib/api/client.ts` (envelope-aware, bearer-token injection). No raw `fetch` in components.
- **Auth is Supabase (ADR-009).** No Solus login/signup endpoints. Config comes from `VITE_SUPABASE_*` env (see `.env.example`); absent env = dev bypass. Never hardcode keys.
- **SOL mode is universal (ADR-016).** Read `settingsStore.solMode`; every natural-language surface respects it.
- **State:** Zustand. Updates are immutable (spread, never mutate). Pure selectors exported for testing (see `features/onboarding/onboardingStore.ts`).
- **No `console.*`** in committed code (H8/lint).

## Testing

- Vitest + Testing Library, jsdom. `pnpm test` (run) / `pnpm test:watch`.
- Tests live next to source as `*.test.ts(x)`. Pure data modules are named `*.constants.ts` / `*.types.ts`.
- The quality hooks run from the git root; `vitest` is a root devDependency and `vitest.config.ts` at the root registers this package as a project. **Pinned to vitest 3** (vite 7 needs ≥3). Known harness gap: hook H9's `vitest run --silent <file>` is incompatible with vitest 3's `--silent` parsing and emits non-blocking noise per test edit — verify with `npx vitest related --run <file>` (what the H10 Stop gate uses). Flag to a human; do not edit hooks.

## Verifying visually

`pnpm build` then serve `out/renderer/` statically (the renderer runs standalone — no Electron main API is used by the auth/onboarding screens). Hash routes: `#/`, `#/login`, `#/signup`, `#/onboarding`.
