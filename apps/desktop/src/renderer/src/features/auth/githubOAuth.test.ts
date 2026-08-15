import { describe, it, expect, vi } from 'vitest'
import type { SupabaseClient } from '@supabase/supabase-js'
import { runGithubOAuth, type OAuthBridge } from './githubOAuth'

function makeSupabase(overrides: {
  signInWithOAuth?: ReturnType<typeof vi.fn>
  exchangeCodeForSession?: ReturnType<typeof vi.fn>
}): SupabaseClient {
  return {
    auth: {
      signInWithOAuth:
        overrides.signInWithOAuth ??
        vi.fn().mockResolvedValue({ data: { url: 'https://gh/authorize' }, error: null }),
      exchangeCodeForSession:
        overrides.exchangeCodeForSession ?? vi.fn().mockResolvedValue({ data: {}, error: null })
    }
  } as unknown as SupabaseClient
}

function makeBridge(overrides: Partial<OAuthBridge> = {}): OAuthBridge {
  return {
    getRedirectUrl: vi.fn().mockResolvedValue('http://localhost:53682/auth/callback'),
    awaitGithub: vi.fn().mockResolvedValue({ code: 'auth-code-1' }),
    getConnectorRedirectUrl: vi.fn().mockResolvedValue('http://localhost:53682/auth/callback'),
    awaitOAuth: vi.fn().mockResolvedValue({ code: 'auth-code-1' }),
    ...overrides
  }
}

describe('runGithubOAuth', () => {
  it('runs the full happy path and exchanges the code', async () => {
    const exchange = vi.fn().mockResolvedValue({ data: {}, error: null })
    const supabase = makeSupabase({ exchangeCodeForSession: exchange })
    const bridge = makeBridge()

    const result = await runGithubOAuth(supabase, bridge)

    expect(result).toEqual({})
    expect(bridge.getRedirectUrl).toHaveBeenCalled()
    expect(supabase.auth.signInWithOAuth).toHaveBeenCalledWith({
      provider: 'github',
      options: { skipBrowserRedirect: true, redirectTo: 'http://localhost:53682/auth/callback' }
    })
    expect(bridge.awaitGithub).toHaveBeenCalledWith('https://gh/authorize')
    expect(exchange).toHaveBeenCalledWith('auth-code-1')
  })

  it('returns the Supabase error if the authorize URL fails', async () => {
    const supabase = makeSupabase({
      signInWithOAuth: vi.fn().mockResolvedValue({ data: null, error: { message: 'provider off' } })
    })
    expect(await runGithubOAuth(supabase, makeBridge())).toEqual({ error: 'provider off' })
  })

  it('surfaces a callback error from the browser round-trip', async () => {
    const bridge = makeBridge({
      awaitGithub: vi.fn().mockResolvedValue({ error: 'Sign-in timed out.' })
    })
    expect(await runGithubOAuth(makeSupabase({}), bridge)).toEqual({ error: 'Sign-in timed out.' })
  })

  it('treats a missing code as a cancellation', async () => {
    const bridge = makeBridge({ awaitGithub: vi.fn().mockResolvedValue({}) })
    expect(await runGithubOAuth(makeSupabase({}), bridge)).toEqual({
      error: 'GitHub sign-in was cancelled.'
    })
  })

  it('returns the exchange error when the code is rejected', async () => {
    const supabase = makeSupabase({
      exchangeCodeForSession: vi
        .fn()
        .mockResolvedValue({ data: {}, error: { message: 'bad code' } })
    })
    expect(await runGithubOAuth(supabase, makeBridge())).toEqual({ error: 'bad code' })
  })
})
