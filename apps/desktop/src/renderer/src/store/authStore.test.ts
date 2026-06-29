import { describe, it, expect, beforeEach } from 'vitest'
import { useAuthStore } from './authStore'

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
})
