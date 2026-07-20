// Production auth guard (SOLUSDEV-152 WS-D, CLAUDE.md §7).
//
// A production build without Supabase env would ship the dev fake-login bypass
// (UI appears authenticated; every API call 401s). This module holds the pure,
// testable logic behind two mechanical defenses:
//
//   1. Build-time: electron.vite.config.ts calls `assertProdAuthEnv` from a
//      renderer plugin, failing any production build with missing/blank vars.
//   2. Bundle-level: `isDevBypassAllowed` is the single decision function for
//      the bypass; branch sites additionally gate on the literal
//      `import.meta.env.DEV` so Vite dead-code-eliminates them in prod.
//
// Pure module: no import.meta, no side effects — importable from both the
// renderer and the Node build config.

/** The env vars a production build must carry for real Supabase auth. */
export const REQUIRED_SUPABASE_ENV_VARS = ['VITE_SUPABASE_URL', 'VITE_SUPABASE_ANON_KEY'] as const

export type RequiredSupabaseEnvVar = (typeof REQUIRED_SUPABASE_ENV_VARS)[number]

/** Env as Vite resolves it (`config.env` mixes strings with DEV/PROD booleans). */
export type ResolvedEnv = Readonly<Record<string, unknown>>

function isPresent(value: unknown): boolean {
  return typeof value === 'string' && value.trim().length > 0
}

/** Names of required Supabase vars that are absent, blank, or not strings. */
export function findMissingSupabaseEnv(env: ResolvedEnv): RequiredSupabaseEnvVar[] {
  return REQUIRED_SUPABASE_ENV_VARS.filter((name) => !isPresent(env[name]))
}

/** Actionable build-failure message: what is missing, why it matters, how to fix. */
export function formatMissingSupabaseEnvError(missing: readonly string[], mode: string): string {
  return [
    `[solus-prod-auth-guard] Refusing to build in "${mode}" mode: missing Supabase auth env — ${missing.join(', ')}.`,
    'A production build without these would ship the dev fake-login bypass (CLAUDE.md §7):',
    'the UI would appear authenticated while every API call fails with 401.',
    'Fix: populate .env.mega at the repo root and run `pnpm env:sync` (SOLUSDEV-147),',
    'or export the variables in the build environment.',
    'For local no-auth work use the dev server (`pnpm dev`); an explicit',
    '`electron-vite build --mode development` also skips this check (built bundles',
    'never contain the dev fake login — without env they show a config error).'
  ].join('\n')
}

/**
 * True for the mode `pnpm build` / a release pipeline uses. The gate keys on
 * Vite's resolved MODE, not `isProduction`: electron-vite forces
 * NODE_ENV=production for every `build` command regardless of --mode, so
 * `isProduction` cannot distinguish a release build from an explicit
 * `--mode development` build (which must keep working without the vars).
 */
export function isProductionBuildMode(mode: string): boolean {
  return mode === 'production'
}

/**
 * Fail a production-mode build that lacks Supabase auth config. No-op outside
 * production mode, so the dev server and explicit dev-mode builds keep working
 * without the vars. (Non-production BUILDS are still safe: electron-vite sets
 * NODE_ENV=production for all builds, so `import.meta.env.DEV` is false and
 * the bypass is dead-code-eliminated from every built bundle — without env
 * they surface authStore's explicit configuration error, never fake auth.)
 */
export function assertProdAuthEnv(env: ResolvedEnv, mode: string): void {
  if (!isProductionBuildMode(mode)) return
  const missing = findMissingSupabaseEnv(env)
  if (missing.length > 0) {
    throw new Error(formatMissingSupabaseEnvError(missing, mode))
  }
}

/**
 * The single decision for the fake-login bypass: only a dev build with no
 * Supabase config may use it. Production builds never qualify, regardless of
 * configuration state — misconfiguration must surface as an explicit error,
 * never as fake auth.
 */
export function isDevBypassAllowed(isDevBuild: boolean, isSupabaseConfigured: boolean): boolean {
  return isDevBuild && !isSupabaseConfigured
}
