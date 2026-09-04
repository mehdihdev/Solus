// SOLUSDEV-235 / EXT-05 — ~/.solus/extensions/index.json: the installed-set
// record. Mirrors localState.test.ts: in-memory fs, corrupt → empty,
// newer schema → read-only, byte cap, reserved ids refused.
import { describe, expect, test } from 'vitest'
import {
  emptyExtensionIndex,
  MAX_INDEX_BYTES,
  parseExtensionIndex,
  readExtensionIndex,
  removeInstalled,
  upsertInstalled,
  type InstalledExtension
} from './extensionIndex'
import { fakeExtensionFs } from './testing/fakeExtensionFs'

const ROOT = '/home/tester/.solus/extensions'
const FILE = `${ROOT}/index.json`
const HASH = 'a'.repeat(64)
const ENTRY: InstalledExtension = {
  version: '1.2.0',
  contentHash: HASH,
  installedAt: '2026-09-03T12:00:00.000Z',
  source: 'registry'
}

describe('parseExtensionIndex', () => {
  test('accepts the documented shape, registry and dev entries', () => {
    const value = {
      schema_version: 1,
      installed: {
        bom: ENTRY,
        'my-dev': { ...ENTRY, source: 'dev', devPath: '/ws/my-dev' }
      }
    }
    const parsed = parseExtensionIndex(value)
    expect(parsed.ok).toBe(true)
    if (parsed.ok) expect(Object.keys(parsed.index.installed).sort()).toEqual(['bom', 'my-dev'])
  })

  test('a newer schema_version is reported as newer', () => {
    expect(parseExtensionIndex({ schema_version: 2, installed: {} })).toEqual({
      ok: false,
      reason: 'newer'
    })
  })

  test.each([
    ['not an object', 'x'],
    ['missing installed', { schema_version: 1 }],
    ['unknown top-level field', { schema_version: 1, installed: {}, extra: 1 }],
    ['unsafe id', { schema_version: 1, installed: { 'Bad Id': ENTRY } }],
    // An object LITERAL `{ __proto__: … }` sets the prototype; JSON.parse makes an own key.
    [
      'reserved id',
      JSON.parse(`{"schema_version":1,"installed":{"__proto__":${JSON.stringify(ENTRY)}}}`)
    ],
    ['reserved id (constructor)', { schema_version: 1, installed: { constructor: ENTRY } }],
    ['bad version', { schema_version: 1, installed: { bom: { ...ENTRY, version: '1.0' } } }],
    ['bad hash', { schema_version: 1, installed: { bom: { ...ENTRY, contentHash: 'zz' } } }],
    ['bad source', { schema_version: 1, installed: { bom: { ...ENTRY, source: 'web' } } }],
    ['unknown entry field', { schema_version: 1, installed: { bom: { ...ENTRY, x: 1 } } }],
    ['dev without devPath', { schema_version: 1, installed: { bom: { ...ENTRY, source: 'dev' } } }],
    [
      'registry with devPath',
      { schema_version: 1, installed: { bom: { ...ENTRY, devPath: '/x' } } }
    ],
    [
      'relative devPath',
      { schema_version: 1, installed: { bom: { ...ENTRY, source: 'dev', devPath: 'rel' } } }
    ]
  ])('rejects %s', (_why, value) => {
    expect(parseExtensionIndex(value)).toEqual({ ok: false, reason: 'invalid' })
  })

  test('the installed map has a null prototype (no inherited keys)', () => {
    const parsed = parseExtensionIndex({ schema_version: 1, installed: {} })
    if (!parsed.ok) throw new Error('expected ok')
    expect('toString' in parsed.index.installed).toBe(false)
  })
})

describe('readExtensionIndex', () => {
  test('missing → empty, writable', () => {
    expect(readExtensionIndex(fakeExtensionFs())).toEqual({
      index: emptyExtensionIndex(),
      writable: true
    })
  })

  test('corrupt JSON → empty, writable, never throws', () => {
    const fs = fakeExtensionFs()
    fs.writeFile(FILE, '{ nope', 0o600)
    expect(readExtensionIndex(fs)).toEqual({ index: emptyExtensionIndex(), writable: true })
  })

  test('over the 1 MiB cap → empty, writable', () => {
    const fs = fakeExtensionFs()
    fs.writeFile(FILE, `{"schema_version":1,"installed":{}}${' '.repeat(MAX_INDEX_BYTES)}`, 0o600)
    expect(readExtensionIndex(fs).index.installed).toEqual({})
  })

  test('newer schema → empty, READ-ONLY', () => {
    const fs = fakeExtensionFs()
    fs.writeFile(FILE, JSON.stringify({ schema_version: 9, installed: {} }), 0o600)
    expect(readExtensionIndex(fs).writable).toBe(false)
  })

  test('round-trips a valid file', () => {
    const fs = fakeExtensionFs()
    fs.writeFile(FILE, JSON.stringify({ schema_version: 1, installed: { bom: ENTRY } }), 0o600)
    expect(readExtensionIndex(fs).index.installed.bom).toEqual(ENTRY)
  })
})

describe('upsertInstalled / removeInstalled', () => {
  test('writes atomically via temp+rename with 0600 under 0700 dirs', () => {
    const fs = fakeExtensionFs()
    expect(upsertInstalled('bom', ENTRY, fs)).toBe(true)
    expect(JSON.parse(fs.text(FILE) as string)).toEqual({
      schema_version: 1,
      installed: { bom: ENTRY }
    })
    expect([...fs.files.keys()]).toEqual([FILE]) // no temp litter
    expect(fs.modes.get(FILE)).toBe(0o600)
    expect(fs.modes.get(ROOT)).toBe(0o700)
    expect(fs.modes.get('/home/tester/.solus')).toBe(0o700)
  })

  test('upsert preserves other entries and replaces the same id', () => {
    const fs = fakeExtensionFs()
    upsertInstalled('bom', ENTRY, fs)
    upsertInstalled('cad', { ...ENTRY, version: '0.1.0' }, fs)
    upsertInstalled('bom', { ...ENTRY, version: '2.0.0' }, fs)
    const written = JSON.parse(fs.text(FILE) as string)
    expect(Object.keys(written.installed).sort()).toEqual(['bom', 'cad'])
    expect(written.installed.bom.version).toBe('2.0.0')
  })

  test.each(['__proto__', 'constructor', 'prototype', 'Bad', '../x', ''])(
    'refuses the id %j and writes nothing',
    (id) => {
      const fs = fakeExtensionFs()
      expect(upsertInstalled(id, ENTRY, fs)).toBe(false)
      expect(removeInstalled(id, fs)).toBe(false)
      expect(fs.files.size).toBe(0)
    }
  )

  test('refuses to write over a newer-schema index', () => {
    const fs = fakeExtensionFs()
    fs.writeFile(FILE, JSON.stringify({ schema_version: 9, installed: {} }), 0o600)
    expect(upsertInstalled('bom', ENTRY, fs)).toBe(false)
    expect(JSON.parse(fs.text(FILE) as string).schema_version).toBe(9)
  })

  test('remove drops the entry; removing an absent id is a success', () => {
    const fs = fakeExtensionFs()
    upsertInstalled('bom', ENTRY, fs)
    upsertInstalled('cad', ENTRY, fs)
    expect(removeInstalled('bom', fs)).toBe(true)
    expect(Object.keys(JSON.parse(fs.text(FILE) as string).installed)).toEqual(['cad'])
    expect(removeInstalled('ghost', fs)).toBe(true)
  })

  test('a failed rename removes the temp file and rethrows', () => {
    const fs = fakeExtensionFs({
      rename: () => {
        throw new Error('EXDEV')
      }
    })
    expect(() => upsertInstalled('bom', ENTRY, fs)).toThrow('EXDEV')
    expect(fs.files.size).toBe(0)
  })
})
