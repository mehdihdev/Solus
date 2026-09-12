// SOLUSDEV-252 S3: ~/.solus/config.json `sol` key (docs/architecture/
// sol-window.md §7) over an in-memory fs — never throws, degrades to defaults.
import { describe, it, expect, vi } from 'vitest'
import {
  createSolSettings,
  DEFAULT_SOL_SETTINGS,
  SOL_CONFIG_SCHEMA_VERSION,
  type SolSettingsDeps
} from './solSettings'

function fakeFs(initial: Record<string, string> = {}): {
  deps: SolSettingsDeps
  files: Map<string, string>
  warn: ReturnType<typeof vi.fn>
} {
  const files = new Map(Object.entries(initial))
  const warn = vi.fn()
  return {
    files,
    warn,
    deps: {
      homedir: () => '/home/u',
      readFile: (path) => {
        const v = files.get(path)
        if (v === undefined) throw new Error('ENOENT')
        return v
      },
      writeFile: (path, content) => void files.set(path, content),
      replaceFile: (from, to) => {
        files.set(to, files.get(from) ?? '')
        files.delete(from)
      },
      mkdir: () => {},
      chmod: () => {},
      remove: (path) => void files.delete(path),
      tempSuffix: () => 'abc',
      warn
    }
  }
}

const CONFIG = '/home/u/.solus/config.json'
const GEOMETRY = { x: 10, y: 20, width: 420, height: 640, displayId: 7 }

describe('read', () => {
  it('missing file → defaults, no warning', () => {
    const f = fakeFs()
    expect(createSolSettings(f.deps).get()).toEqual(DEFAULT_SOL_SETTINGS)
    expect(f.warn).not.toHaveBeenCalled()
  })

  it('reads a well-formed file and ignores unknown/invalid fields', () => {
    const f = fakeFs({
      [CONFIG]: JSON.stringify({
        schema_version: 1,
        sol: { actionMode: 'do', screenIntelligence: true, alwaysOnTop: 'yes', window: { x: 1 } }
      })
    })
    expect(createSolSettings(f.deps).get()).toEqual({
      actionMode: 'do',
      screenIntelligence: true,
      hotkeys: true,
      alwaysOnTop: false,
      window: null
    })
  })

  it('hotkeys defaults to true and only an explicit false turns it off (§7 consent surface)', () => {
    expect(DEFAULT_SOL_SETTINGS.hotkeys).toBe(true)
    const off = fakeFs({ [CONFIG]: JSON.stringify({ schema_version: 1, sol: { hotkeys: false } }) })
    expect(createSolSettings(off.deps).get().hotkeys).toBe(false)
    const junk = fakeFs({ [CONFIG]: JSON.stringify({ schema_version: 1, sol: { hotkeys: 'no' } }) })
    expect(createSolSettings(junk.deps).get().hotkeys).toBe(true)
  })

  it('corrupt JSON → defaults + one warning, still writable', () => {
    const f = fakeFs({ [CONFIG]: '{not json' })
    const s = createSolSettings(f.deps)
    expect(s.get()).toEqual(DEFAULT_SOL_SETTINGS)
    expect(f.warn).toHaveBeenCalledTimes(1)
    s.setMode('do')
    expect(JSON.parse(f.files.get(CONFIG) ?? '').sol.actionMode).toBe('do')
  })

  it('a newer schema_version is read-only: defaults, warning, no write', () => {
    const raw = JSON.stringify({ schema_version: SOL_CONFIG_SCHEMA_VERSION + 1, sol: {} })
    const f = fakeFs({ [CONFIG]: raw })
    const s = createSolSettings(f.deps)
    s.setMode('do')
    expect(s.get().actionMode).toBe('do') // in-memory still works for this run
    expect(f.files.get(CONFIG)).toBe(raw)
    expect(f.warn).toHaveBeenCalled()
  })
})

describe('write', () => {
  it('persists every setter atomically and preserves other top-level keys', () => {
    const f = fakeFs({ [CONFIG]: JSON.stringify({ schema_version: 1, other: { keep: true } }) })
    const s = createSolSettings(f.deps)
    s.setScreenIntelligence(true)
    s.setHotkeys(false)
    s.setAlwaysOnTop(true)
    s.setWindowGeometry(GEOMETRY)
    const doc = JSON.parse(f.files.get(CONFIG) ?? '')
    expect(doc.other).toEqual({ keep: true })
    expect(doc.schema_version).toBe(SOL_CONFIG_SCHEMA_VERSION)
    expect(doc.sol).toEqual({
      actionMode: 'guide',
      screenIntelligence: true,
      hotkeys: false,
      alwaysOnTop: true,
      window: GEOMETRY
    })
    expect([...f.files.keys()]).toEqual([CONFIG]) // no temp litter
    expect(createSolSettings(f.deps).get()).toEqual(doc.sol)
  })

  it('toggleMode flips guide ↔ do and returns the new mode', () => {
    const s = createSolSettings(fakeFs().deps)
    expect(s.toggleMode()).toBe('do')
    expect(s.toggleMode()).toBe('guide')
  })

  it('a failing write warns and never throws', () => {
    const f = fakeFs()
    f.deps.writeFile = () => {
      throw new Error('EACCES')
    }
    const s = createSolSettings(f.deps)
    expect(() => s.setMode('do')).not.toThrow()
    expect(s.get().actionMode).toBe('do')
    expect(f.warn).toHaveBeenCalledTimes(1)
  })
})

describe('onChange', () => {
  it('fires with the new state after each change; unsubscribe stops it', () => {
    const s = createSolSettings(fakeFs().deps)
    const cb = vi.fn()
    const off = s.onChange(cb)
    s.setMode('do')
    expect(cb).toHaveBeenCalledWith(expect.objectContaining({ actionMode: 'do' }))
    off()
    s.setAlwaysOnTop(true)
    expect(cb).toHaveBeenCalledTimes(1)
  })
})
