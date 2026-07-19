import { describe, it, expect, beforeEach } from 'vitest'
import type { User as SupabaseUser } from '@supabase/supabase-js'
import { useAuthStore, toAuthUser } from './authStore'

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
