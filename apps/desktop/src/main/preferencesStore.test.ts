// SOLUSDEV-244 / HOME H3: ~/.solus/preferences.json — the user's engineering
// preferences (ADR-034 amendment 2026-09-06). Parsed strictly in THIS process,
// byte-gated before materializing, atomic temp+rename writes, 0600 under the
// 0700 home, a newer schema_version's file is read-only, corrupt ⇒ empty.
import {
  ENGINEERING_PREFERENCES_SCHEMA_VERSION,
  PREFERENCES_FIELD_CAP,
  PREFERENCES_MAX_BYTES,
  emptyEngineeringPreferences,
  type EngineeringPreferences
} from '@solus/shared-types'
import { mkdtempSync, mkdirSync, symlinkSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  preferencesIpc,
  readPreferences,
  realPreferencesStoreDeps,
  writePreferences,
  type PreferencesStoreDeps
} from './preferencesStore'

interface Memory {
  deps: PreferencesStoreDeps
  files: Map<string, string>
  modes: Map<string, number>
  renames: Array<{ from: string; to: string }>
}

function memoryDeps(): Memory {
  const files = new Map<string, string>()
  const modes = new Map<string, number>()
  const renames: Array<{ from: string; to: string }> = []
  const deps: PreferencesStoreDeps = {
    homedir: () => '/home/u',
    readFile: (path) => {
      const content = files.get(path)
      if (content === undefined) throw new Error('ENOENT')
      return content
    },
    writeFile: (path, content, mode) => {
      files.set(path, content)
      modes.set(path, mode)
    },
    replaceFile: (from, to) => {
      const content = files.get(from)
      if (content === undefined) throw new Error('ENOENT')
      files.delete(from)
      files.set(to, content)
      renames.push({ from, to })
    },
    mkdir: () => undefined,
    chmod: (path, mode) => void modes.set(path, mode),
    fileSize: (path) => {
      const content = files.get(path)
      return content === undefined ? null : Buffer.byteLength(content, 'utf8')
    },
    now: () => new Date('2026-09-06T12:00:00Z')
  }
  return { deps, files, modes, renames }
}

const PATH = '/home/u/.solus/preferences.json'
const DOC: EngineeringPreferences = {
  ...emptyEngineeringPreferences(),
  freeText: 'Prefer 0.1 mm clearance minimum on all boards.',
  electrical: 'JST-GH for signal.'
}

describe('preferencesStore', () => {
  registerPreferencesDiskPersistenceTests()
  registerPreferencesDiskFailuresTests()
})

describe('preferencesIpc (the gate itself is tested)', () => {
  it('refuses a foreign sender on both channels', () => {
    const m = memoryDeps()
    writePreferences(DOC, m.deps)
    expect(preferencesIpc.read(false, m.deps)).toBeNull()
    expect(preferencesIpc.write(false, emptyEngineeringPreferences(), m.deps)).toEqual({
      ok: false
    })
    expect(readPreferences(m.deps).preferences.freeText).toBe(DOC.freeText)
  })

  it('serves the document to the app renderer and re-validates what it writes', () => {
    const m = memoryDeps()
    expect(preferencesIpc.read(true, m.deps)).toEqual({
      preferences: emptyEngineeringPreferences(),
      readOnly: false
    })
    expect(preferencesIpc.write(true, 'not a document', m.deps)).toEqual({ ok: false })
    expect(preferencesIpc.write(true, DOC, m.deps)).toEqual({ ok: true })
    expect(preferencesIpc.read(true, m.deps)?.preferences.electrical).toBe(DOC.electrical)
  })
})

describe('realPreferencesStoreDeps (SEC review L7 — the symlink refusal is real code)', () => {
  it('sizes only a regular file; a symlink or a directory reads as absent', () => {
    const dir = mkdtempSync(join(tmpdir(), 'solus-prefs-'))
    try {
      const regular = join(dir, 'regular.json')
      writeFileSync(regular, '{"schema_version":1}')
      const link = join(dir, 'link.json')
      symlinkSync(regular, link)
      const folder = join(dir, 'folder.json')
      mkdirSync(folder)
      expect(realPreferencesStoreDeps.fileSize(regular)).toBe(20)
      expect(realPreferencesStoreDeps.fileSize(link)).toBeNull()
      expect(realPreferencesStoreDeps.fileSize(folder)).toBeNull()
      expect(realPreferencesStoreDeps.fileSize(join(dir, 'missing.json'))).toBeNull()
      // And the temp write is exclusive: a planted file at the temp path is refused.
      expect(() => realPreferencesStoreDeps.writeFile(regular, 'x', 0o600)).toThrow()
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})

function registerPreferencesDiskPersistenceTests(): void {
  it('reads the empty document when no file exists — never throws', () => {
    const m = memoryDeps()
    expect(readPreferences(m.deps)).toEqual({
      preferences: emptyEngineeringPreferences(),
      readOnly: false
    })
  })

  it('round-trips a document atomically, 0600, with updatedAt stamped', () => {
    const m = memoryDeps()
    expect(writePreferences(DOC, m.deps)).toBe(true)
    expect(m.renames).toHaveLength(1)
    expect(m.renames[0].to).toBe(PATH)
    expect(m.renames[0].from).not.toBe(PATH)
    expect(m.renames[0].from.startsWith('/home/u/.solus/')).toBe(true)
    expect(m.modes.get(PATH)).toBe(0o600)
    expect(m.modes.get('/home/u/.solus')).toBe(0o700)
    const stored = JSON.parse(m.files.get(PATH) ?? '{}') as Record<string, unknown>
    expect(stored.schema_version).toBe(ENGINEERING_PREFERENCES_SCHEMA_VERSION)
    expect(stored.updatedAt).toBe('2026-09-06T12:00:00.000Z')
    expect(readPreferences(m.deps)).toEqual({
      preferences: { ...DOC, updatedAt: '2026-09-06T12:00:00.000Z' },
      readOnly: false
    })
  })

  it('treats a corrupt or oversized file as the empty document', () => {
    const m = memoryDeps()
    m.files.set(PATH, '{not json')
    expect(readPreferences(m.deps).preferences).toEqual(emptyEngineeringPreferences())
    m.files.set(PATH, JSON.stringify({ ...DOC, toggles: { darkMode: true } }))
    expect(readPreferences(m.deps).preferences).toEqual(emptyEngineeringPreferences())
    m.files.set(PATH, '指'.repeat(Math.ceil(PREFERENCES_MAX_BYTES / 3) + 10))
    expect(readPreferences(m.deps).preferences).toEqual(emptyEngineeringPreferences())
    // Not a regular file (fileSize null models a symlink planted at the path).
    m.files.set(PATH, JSON.stringify(DOC))
    expect(readPreferences({ ...m.deps, fileSize: () => null }).preferences).toEqual(
      emptyEngineeringPreferences()
    )
  })

  it('never clobbers a NEWER schema_version file and reports it read-only', () => {
    const m = memoryDeps()
    const newer = JSON.stringify({ ...DOC, schema_version: 2 })
    m.files.set(PATH, newer)
    expect(readPreferences(m.deps)).toEqual({
      preferences: emptyEngineeringPreferences(),
      readOnly: true
    })
    expect(writePreferences(DOC, m.deps)).toBe(false)
    expect(m.files.get(PATH)).toBe(newer)
  })

  it('caps every field on write so the file can never exceed the prompt budget', () => {
    const m = memoryDeps()
    const oversized = { ...DOC, mechanical: 'm'.repeat(PREFERENCES_FIELD_CAP + 500) }
    expect(writePreferences(oversized, m.deps)).toBe(true)
    expect(readPreferences(m.deps).preferences.mechanical).toHaveLength(PREFERENCES_FIELD_CAP)
  })
}

function registerPreferencesDiskFailuresTests(): void {
  it('refuses a malformed document instead of writing it', () => {
    const m = memoryDeps()
    expect(
      writePreferences({ ...DOC, electrical: 3 } as unknown as EngineeringPreferences, m.deps)
    ).toBe(false)
    expect(writePreferences(null as unknown as EngineeringPreferences, m.deps)).toBe(false)
    expect(m.files.size).toBe(0)
  })

  it('reports false when the filesystem fails, never throws', () => {
    const m = memoryDeps()
    const deps = {
      ...m.deps,
      writeFile: () => {
        throw new Error('EACCES')
      }
    }
    expect(writePreferences(DOC, deps)).toBe(false)
  })
}
