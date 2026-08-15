import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import type { User as SupabaseUser } from '@supabase/supabase-js'
import { useAuthStore, toAuthUser } from './authStore'
import { getDesktopCompanionBridge } from '../lib/desktopBridge'

// The companion token relay (SOLUSDEV-154 / BRG-04) is mocked so we can assert
// setSession fires it; everywhere else it resolves to no bridge (non-Electron).
vi.mock('../lib/desktopBridge', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/desktopBridge')>()
  return { ...actual, getDesktopCompanionBridge: vi.fn(() => null) }
})

// With no Supabase env in the test environment, the store runs its dev-bypass
// path — exactly what keeps the prototype demoable offline.

describe('authStore (dev bypass)', () => {
  beforeEach(() => {
    useAuthStore.setState({
      status: 'loading',
      user: null,
      accessToken: null,
      onboarded: false
    })
  })

  it('setSession marks the user authenticated', () => {
    useAuthStore.getState().setSession({ email: 'maya@strider.dev' }, 'tok')
    const s = useAuthStore.getState()
    expect(s.status).toBe('authenticated')
    expect(s.user?.email).toBe('maya@strider.dev')
    expect(s.accessToken).toBe('tok')
  })

  it('setSession(null) marks the user unauthenticated', () => {
    useAuthStore.getState().setSession(null, null)
    expect(useAuthStore.getState().status).toBe('unauthenticated')
  })

  it('signUpWithPassword authenticates via dev bypass', async () => {
    const result = await useAuthStore.getState().signUpWithPassword('a@b.dev', 'hunter22')
    expect(result.error).toBeUndefined()
    expect(useAuthStore.getState().user?.email).toBe('a@b.dev')
    expect(useAuthStore.getState().status).toBe('authenticated')
  })

  it('signInWithGitHub authenticates via dev bypass', async () => {
    await useAuthStore.getState().signInWithGitHub()
    expect(useAuthStore.getState().status).toBe('authenticated')
  })

  it('completeOnboarding flips the onboarded flag', () => {
    expect(useAuthStore.getState().onboarded).toBe(false)
    useAuthStore.getState().completeOnboarding()
    expect(useAuthStore.getState().onboarded).toBe(true)
  })

  it('signOut clears session and onboarding', async () => {
    useAuthStore.getState().setSession({ email: 'x@y.dev' }, 'tok')
    useAuthStore.getState().completeOnboarding()
    await useAuthStore.getState().signOut()
    const s = useAuthStore.getState()
    expect(s.user).toBeNull()
    expect(s.status).toBe('unauthenticated')
    expect(s.onboarded).toBe(false)
  })

  it('bootstrap resolves to unauthenticated with no persisted user', async () => {
    await useAuthStore.getState().bootstrap()
    expect(useAuthStore.getState().status).toBe('unauthenticated')
  })

  it('teardown is safe to call (no Supabase listener in dev bypass)', () => {
    expect(() => useAuthStore.getState().teardown()).not.toThrow()
  })

  it('requestPasswordReset resolves without error in dev bypass', async () => {
    const result = await useAuthStore.getState().requestPasswordReset('a@b.dev')
    expect(result.error).toBeUndefined()
  })

  it('confirmPasswordReset resolves without error in dev bypass', async () => {
    const result = await useAuthStore
      .getState()
      .confirmPasswordReset('a@b.dev', '123456', 'newpass1')
    expect(result.error).toBeUndefined()
  })
})

// SOLUSDEV-152 WS-D: the bypass branch is gated on the literal `import.meta.env.DEV`
// read at call time. Stubbing DEV=false exercises exactly the gate a production
// bundle folds to `false` (and then dead-code-eliminates — see the build proof).
describe('authStore (production build gate, SOLUSDEV-152)', () => {
  beforeEach(() => {
    vi.stubEnv('DEV', false)
    useAuthStore.setState({
      status: 'loading',
      user: null,
      accessToken: null,
      onboarded: false
    })
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  function expectNoSession(): void {
    const s = useAuthStore.getState()
    expect(s.user).toBeNull()
    expect(s.accessToken).toBeNull()
    expect(s.status).not.toBe('authenticated')
  }

  it('signUpWithPassword surfaces a configuration error instead of fake auth', async () => {
    const result = await useAuthStore.getState().signUpWithPassword('a@b.dev', 'hunter22')
    expect(result.error).toMatch(/configuration/i)
    expectNoSession()
  })

  it('signInWithPassword surfaces a configuration error instead of fake auth', async () => {
    const result = await useAuthStore.getState().signInWithPassword('a@b.dev', 'hunter22')
    expect(result.error).toMatch(/configuration/i)
    expectNoSession()
  })

  it('signInWithGitHub surfaces a configuration error instead of fake auth', async () => {
    const result = await useAuthStore.getState().signInWithGitHub()
    expect(result.error).toMatch(/configuration/i)
    expectNoSession()
  })

  it('sendMagicLink surfaces a configuration error instead of fake auth', async () => {
    const result = await useAuthStore.getState().sendMagicLink('a@b.dev')
    expect(result.error).toMatch(/configuration/i)
    expectNoSession()
  })

  it('resendConfirmation surfaces a configuration error instead of silent success', async () => {
    const result = await useAuthStore.getState().resendConfirmation('a@b.dev')
    expect(result.error).toMatch(/configuration/i)
  })

  it('requestPasswordReset surfaces a configuration error instead of silent success', async () => {
    const result = await useAuthStore.getState().requestPasswordReset('a@b.dev')
    expect(result.error).toMatch(/configuration/i)
  })

  it('confirmPasswordReset surfaces a configuration error instead of silent success', async () => {
    const result = await useAuthStore
      .getState()
      .confirmPasswordReset('a@b.dev', '123456', 'newpass1')
    expect(result.error).toMatch(/configuration/i)
  })

  it('bootstrap never trusts a locally-persisted session', async () => {
    useAuthStore.setState({
      user: { email: 'ghost@solus.local' },
      accessToken: 'stale-token',
      status: 'loading',
      onboarded: true
    })
    await useAuthStore.getState().bootstrap()
    const s = useAuthStore.getState()
    expect(s.status).toBe('unauthenticated')
    expect(s.user).toBeNull()
    expect(s.accessToken).toBeNull()
  })
})

// SOLUSDEV-154 / BRG-04: setSession is the single choke point for token
// changes (sign-in, TOKEN_REFRESHED, sign-out) — every call relays the token
// to the local companion, fire-and-forget.
describe('authStore companion token relay', () => {
  beforeEach(() => {
    useAuthStore.setState({
      status: 'loading',
      user: null,
      accessToken: null,
      onboarded: false
    })
    vi.mocked(getDesktopCompanionBridge).mockReset()
    vi.mocked(getDesktopCompanionBridge).mockReturnValue(null)
  })

  it('relays the access token to the companion on setSession', () => {
    const setToken = vi.fn().mockResolvedValue(undefined)
    vi.mocked(getDesktopCompanionBridge).mockReturnValue({ setToken, setProject: vi.fn().mockResolvedValue(undefined) })
    useAuthStore.getState().setSession({ email: 'maya@strider.dev' }, 'sb-token')
    expect(setToken).toHaveBeenCalledWith('sb-token')
  })

  it('relays null (signout) when the session is cleared', () => {
    const setToken = vi.fn().mockResolvedValue(undefined)
    vi.mocked(getDesktopCompanionBridge).mockReturnValue({ setToken, setProject: vi.fn().mockResolvedValue(undefined) })
    useAuthStore.getState().setSession(null, null)
    expect(setToken).toHaveBeenCalledWith(null)
  })

  it('is a no-op outside Electron and never blocks the session update', () => {
    useAuthStore.getState().setSession({ email: 'maya@strider.dev' }, 'sb-token')
    expect(useAuthStore.getState().status).toBe('authenticated')
  })

  it('swallows relay failures without touching session state', () => {
    const setToken = vi.fn().mockRejectedValue(new Error('ipc down'))
    vi.mocked(getDesktopCompanionBridge).mockReturnValue({ setToken, setProject: vi.fn().mockResolvedValue(undefined) })
    useAuthStore.getState().setSession({ email: 'maya@strider.dev' }, 'sb-token')
    expect(useAuthStore.getState().accessToken).toBe('sb-token')
  })
})

describe('toAuthUser', () => {
  const base = { id: 'u1', app_metadata: {}, user_metadata: {}, aud: '', created_at: '' }

  it('returns null when there is no email', () => {
    expect(toAuthUser(null)).toBeNull()
    expect(toAuthUser({ ...base, email: undefined } as unknown as SupabaseUser)).toBeNull()
  })

  it('marks a confirmed email verified', () => {
    const user = { ...base, email: 'a@b.dev', email_confirmed_at: '2026-01-01T00:00:00Z' }
    expect(toAuthUser(user as SupabaseUser)?.emailVerified).toBe(true)
  })

  it('marks an unconfirmed email unverified', () => {
    const user = { ...base, email: 'a@b.dev' }
    expect(toAuthUser(user as SupabaseUser)?.emailVerified).toBe(false)
  })

  it('honors an email_verified flag in user_metadata', () => {
    const user = { ...base, email: 'a@b.dev', user_metadata: { email_verified: true } }
    expect(toAuthUser(user as SupabaseUser)?.emailVerified).toBe(true)
  })
})
