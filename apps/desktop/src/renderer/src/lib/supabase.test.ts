import { describe, it, expect } from 'vitest'
import {
  isConfigured,
  buildSupabaseClient,
  supabase,
  supabaseConfigured,
  devBypassActive
} from './supabase'

describe('isConfigured', () => {
  it('is true only when both url and key are present', () => {
    expect(isConfigured('https://x.supabase.co', 'anon-key')).toBe(true)
  })

  it('is false when either is missing or blank', () => {
    expect(isConfigured(undefined, 'k')).toBe(false)
    expect(isConfigured('https://x.supabase.co', undefined)).toBe(false)
    expect(isConfigured('   ', 'k')).toBe(false)
    expect(isConfigured('https://x.supabase.co', '  ')).toBe(false)
    expect(isConfigured(undefined, undefined)).toBe(false)
  })
})

describe('devBypassActive (SOLUSDEV-152)', () => {
  it('is active in the dev/test environment when Supabase env is absent', () => {
    // vitest.config.ts blanks VITE_SUPABASE_* and DEV=true under vitest, so the
    // bypass must be on — this pins the dev UX the guard must not break.
    expect(supabaseConfigured).toBe(false)
    expect(supabase).toBeNull()
    expect(devBypassActive).toBe(true)
  })
})

describe('buildSupabaseClient', () => {
  it('returns null when not configured (dev bypass)', () => {
    expect(buildSupabaseClient(undefined, undefined)).toBeNull()
  })

  it('returns a client with an auth namespace when configured', () => {
    const client = buildSupabaseClient('https://x.supabase.co', 'anon-key')
    expect(client).not.toBeNull()
    expect(client?.auth).toBeDefined()
  })
})
