import { describe, it, expect } from 'vitest'
import {
  REQUIRED_SUPABASE_ENV_VARS,
  findMissingSupabaseEnv,
  formatMissingSupabaseEnvError,
  isProductionBuildMode,
  assertProdAuthEnv,
  isDevBypassAllowed
} from './prodAuthGuard'

const FULL_ENV = {
  VITE_SUPABASE_URL: 'https://example.supabase.co',
  VITE_SUPABASE_ANON_KEY: 'anon-key'
}

describe('REQUIRED_SUPABASE_ENV_VARS', () => {
  it('names exactly the two Supabase auth vars', () => {
    expect(REQUIRED_SUPABASE_ENV_VARS).toEqual(['VITE_SUPABASE_URL', 'VITE_SUPABASE_ANON_KEY'])
  })
})

describe('findMissingSupabaseEnv', () => {
  it('returns an empty list when both vars are present', () => {
    expect(findMissingSupabaseEnv(FULL_ENV)).toEqual([])
  })

  it('returns both names when the env is empty', () => {
    expect(findMissingSupabaseEnv({})).toEqual(['VITE_SUPABASE_URL', 'VITE_SUPABASE_ANON_KEY'])
  })

  it('returns only the missing var when one is absent', () => {
    expect(findMissingSupabaseEnv({ VITE_SUPABASE_URL: FULL_ENV.VITE_SUPABASE_URL })).toEqual([
      'VITE_SUPABASE_ANON_KEY'
    ])
  })

  it('treats blank and whitespace-only values as missing', () => {
    expect(
      findMissingSupabaseEnv({ VITE_SUPABASE_URL: '   ', VITE_SUPABASE_ANON_KEY: '' })
    ).toEqual(['VITE_SUPABASE_URL', 'VITE_SUPABASE_ANON_KEY'])
  })

  it('treats non-string values (e.g. booleans from config.env) as missing', () => {
    expect(findMissingSupabaseEnv({ VITE_SUPABASE_URL: true, VITE_SUPABASE_ANON_KEY: 42 })).toEqual(
      ['VITE_SUPABASE_URL', 'VITE_SUPABASE_ANON_KEY']
    )
  })
})

describe('formatMissingSupabaseEnvError', () => {
  it('names every missing var and the build mode', () => {
    const message = formatMissingSupabaseEnvError(
      ['VITE_SUPABASE_URL', 'VITE_SUPABASE_ANON_KEY'],
      'production'
    )
    expect(message).toContain('VITE_SUPABASE_URL')
    expect(message).toContain('VITE_SUPABASE_ANON_KEY')
    expect(message).toContain('production')
  })

  it('names the one env file to fix and how to build without auth (dev mode)', () => {
    const message = formatMissingSupabaseEnvError(['VITE_SUPABASE_ANON_KEY'], 'production')
    expect(message).toContain('.env at the repo root')
    expect(message).toContain('--mode development')
  })
})

describe('isProductionBuildMode', () => {
  it('is true only for the "production" mode', () => {
    expect(isProductionBuildMode('production')).toBe(true)
    expect(isProductionBuildMode('development')).toBe(false)
    expect(isProductionBuildMode('test')).toBe(false)
  })
})

describe('assertProdAuthEnv', () => {
  it('throws in a production-mode build when both vars are missing', () => {
    expect(() => assertProdAuthEnv({}, 'production')).toThrowError(
      /VITE_SUPABASE_URL[\s\S]*VITE_SUPABASE_ANON_KEY|VITE_SUPABASE_URL.*VITE_SUPABASE_ANON_KEY/
    )
  })

  it('throws in a production-mode build when a var is blank', () => {
    expect(() =>
      assertProdAuthEnv({ ...FULL_ENV, VITE_SUPABASE_ANON_KEY: '  ' }, 'production')
    ).toThrowError(/VITE_SUPABASE_ANON_KEY/)
  })

  it('passes a production-mode build when both vars are present', () => {
    expect(() => assertProdAuthEnv(FULL_ENV, 'production')).not.toThrow()
  })

  it('never throws outside production mode, even with an empty env (dev server, dev-mode build)', () => {
    expect(() => assertProdAuthEnv({}, 'development')).not.toThrow()
    expect(() => assertProdAuthEnv({}, 'test')).not.toThrow()
  })
})

describe('isDevBypassAllowed', () => {
  it('allows the bypass only in a dev build with no Supabase config', () => {
    expect(isDevBypassAllowed(true, false)).toBe(true)
  })

  it('never allows the bypass when Supabase is configured', () => {
    expect(isDevBypassAllowed(true, true)).toBe(false)
  })

  it('never allows the bypass in a production build (the SOLUSDEV-152 invariant)', () => {
    expect(isDevBypassAllowed(false, false)).toBe(false)
    expect(isDevBypassAllowed(false, true)).toBe(false)
  })
})
