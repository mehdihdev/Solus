// GitHub OAuth orchestration for the desktop loopback flow. Deps (the Supabase
// client and the Electron bridge) are injected so this is unit-testable.
//
// Steps: get the loopback redirect URL from main → ask Supabase for the GitHub
// authorize URL (PKCE, no auto-redirect) → hand it to main, which opens the
// system browser and captures the callback → exchange the returned code for a
// session. The session lands via the client's onAuthStateChange listener.
import type { SupabaseClient } from '@supabase/supabase-js'

export interface OAuthBridge {
  /** Sign-in flow: a per-flow redirect URL carrying our own CSRF nonce. */
  getRedirectUrl: () => Promise<string>
  awaitGithub: (authorizeUrl: string) => Promise<{ code?: string; error?: string }>
  /** Connector flow: a CONSTANT redirect URL (strict providers such as Onshape
   *  match the registered URI exactly), with the backend's OAuth state as the
   *  nonce the provider echoes back. */
  getConnectorRedirectUrl: () => Promise<string>
  awaitOAuth: (
    authorizeUrl: string,
    expectedState: string
  ) => Promise<{ code?: string; error?: string }>
}

export interface GithubOAuthResult {
  error?: string
}

export async function runGithubOAuth(
  supabase: SupabaseClient,
  bridge: OAuthBridge
): Promise<GithubOAuthResult> {
  const redirectTo = await bridge.getRedirectUrl()

  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: 'github',
    options: { skipBrowserRedirect: true, redirectTo }
  })
  if (error) return { error: error.message }
  if (!data?.url) return { error: 'Could not start GitHub sign-in.' }

  const callback = await bridge.awaitGithub(data.url)
  if (callback.error) return { error: callback.error }
  if (!callback.code) return { error: 'GitHub sign-in was cancelled.' }

  const exchange = await supabase.auth.exchangeCodeForSession(callback.code)
  if (exchange.error) return { error: exchange.error.message }
  return {}
}
