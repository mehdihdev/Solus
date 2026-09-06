// SOLUSDEV-235 / EXT-05 — bytes → decoded TOML → contract parse, with caps.
import { describe, expect, test } from 'vitest'
import { loadManifestFromBytes, MAX_MANIFEST_BYTES } from './manifestToml'
import { manifestToml } from './testing/zipBuilder'

const enc = (s: string): Uint8Array => new TextEncoder().encode(s)

describe('loadManifestFromBytes', () => {
  test('parses a valid manifest through the contract', () => {
    const result = loadManifestFromBytes(enc(manifestToml('bom', '1.2.0')))
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.manifest.extension.id).toBe('bom')
      expect(result.manifest.permissions.network).toEqual(['https://api.example.com'])
    }
  })

  test('surfaces TOML syntax errors as extension.toml problems', () => {
    const result = loadManifestFromBytes(enc('schema_version = \n[[['))
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.reason).toBe('invalid')
      expect(result.problems[0]).toMatch(/^extension\.toml: /)
    }
  })

  test('surfaces contract problems with their dotted paths', () => {
    const result = loadManifestFromBytes(enc(manifestToml('Bad Id', '1.2.0')))
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.problems.some((p) => p.startsWith('extension.id:'))).toBe(true)
  })

  test('reports a newer schema as newer (read-only for this build)', () => {
    const result = loadManifestFromBytes(
      enc(manifestToml().replace('schema_version = 1', 'schema_version = 3'))
    )
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.reason).toBe('newer')
  })

  test('refuses an oversized or non-UTF-8 file before parsing', () => {
    const big = loadManifestFromBytes(new Uint8Array(MAX_MANIFEST_BYTES + 1))
    expect(big.ok).toBe(false)
    if (!big.ok) expect(big.reason).toBe('too_large')
    const bad = loadManifestFromBytes(new Uint8Array([0xff, 0xfe, 0x00, 0xc3]))
    expect(bad.ok).toBe(false)
    if (!bad.ok) expect(bad.reason).toBe('invalid')
  })
})

// SOLUSDEV-246 (STORE ST1): the committed first-party fixture bundle parses
// through the desktop's own loader — the installer and developer mode read
// exactly this text.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('the fixture bundle folder (schema_version 2)', () => {
  const folder = resolve(
    __dirname,
    '../../../../../packages/shared-types/fixtures/extension-bundles/fixture-bundle'
  )

  test('extension.toml loads with the first-party tables intact', () => {
    const result = loadManifestFromBytes(
      new Uint8Array(readFileSync(resolve(folder, 'extension.toml')))
    )
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.manifest.schema_version).toBe(2)
    expect(result.manifest.extension.id).toBe('fixture-bundle')
    expect(result.manifest.views.page?.label).toBe('Fixture')
    expect(result.manifest.backend).toEqual({ capability: 'fixture-bundle', routes: true })
    expect(result.manifest.graph.kinds).toEqual([{ name: 'note', domain: 'code' }])
    expect(result.manifest.tools.names).toEqual(['add_note', 'clear_notes'])
  })
})
