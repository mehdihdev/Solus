import { describe, it, expect } from 'vitest'
import { isConfigured, buildSupabaseClient } from './supabase'

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
