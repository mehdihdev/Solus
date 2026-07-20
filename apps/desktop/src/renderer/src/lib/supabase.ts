// Supabase Auth client (ADR-009). Solus runs no login/signup endpoints of its
// own — signup, magic links, password auth, and GitHub OAuth all happen against
// Supabase from the client; the backend only validates the resulting JWT.
//
// Config comes from env (never hardcoded — CLAUDE.md §7):
//   VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY
// When env is absent in a DEV build the app runs a dev bypass (see authStore),
// so the onboarding prototype stays demoable without a provisioned Supabase
// project. Production builds never bypass (SOLUSDEV-152 WS-D): the build fails
// without env (see electron.vite.config.ts), and if a misconfigured build ever
// ran anyway, authStore surfaces an explicit configuration error — not fake auth.
import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import { isDevBypassAllowed } from './prodAuthGuard'

/** True when both Supabase env vars are present and non-empty. Pure + testable. */
export function isConfigured(url: string | undefined, anonKey: string | undefined): boolean {
  return Boolean(url && url.trim() && anonKey && anonKey.trim())
}

/** Build a Supabase client, or null when not configured. Pure + testable. */
export function buildSupabaseClient(
  url: string | undefined,
  anonKey: string | undefined
): SupabaseClient | null {
  if (!isConfigured(url, anonKey)) return null
  return createClient(url as string, anonKey as string, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      // Electron renderer has no server redirect; we capture the OAuth callback
      // via a loopback localhost server in the main process, then exchange the
      // code here. PKCE keeps the verifier in this client instance.
      detectSessionInUrl: false,
      flowType: 'pkce'
    }
  })
}

const URL_ENV = import.meta.env.VITE_SUPABASE_URL
const KEY_ENV = import.meta.env.VITE_SUPABASE_ANON_KEY

export const supabaseConfigured = isConfigured(URL_ENV, KEY_ENV)

/**
 * True only in a dev build with no Supabase env — the sole state in which the
 * fake-login bypass may exist (SOLUSDEV-152 WS-D). Every bypass branch site in
 * authStore re-checks the literal `import.meta.env.DEV` alongside this flag,
 * so Vite folds the branch to `false` in production bundles and dead-code-
 * eliminates the bypass entirely (proven by the bundle grep in the WS-D report).
 */
export const devBypassActive: boolean = isDevBypassAllowed(import.meta.env.DEV, supabaseConfigured)

/**
 * Singleton Supabase client for the app. Null means "not configured": in a dev
 * build that enables the bypass; in a production build it is a packaging error
 * that authStore surfaces as an explicit configuration failure.
 */
export const supabase: SupabaseClient | null = buildSupabaseClient(URL_ENV, KEY_ENV)
