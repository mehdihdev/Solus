// Supabase Auth client (ADR-009). Solus runs no login/signup endpoints of its
// own — signup, magic links, password auth, and GitHub OAuth all happen against
// Supabase from the client; the backend only validates the resulting JWT.
//
// Config comes from env (never hardcoded — CLAUDE.md §7):
//   VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY
// When env is absent the app runs in a dev bypass (see authStore), so the
// onboarding prototype stays demoable without a provisioned Supabase project.
import { createClient, type SupabaseClient } from '@supabase/supabase-js'

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

/** Singleton Supabase client for the app, or null in dev bypass. */
export const supabase: SupabaseClient | null = buildSupabaseClient(URL_ENV, KEY_ENV)
