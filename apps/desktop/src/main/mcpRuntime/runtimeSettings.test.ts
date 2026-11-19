// SOLUSDEV-329 — `~/.solus/config.json` → `mcp_runtime`
// (docs/architecture/mcp-fork-runtime.md §8, docs/contracts/local-state.md).
import { describe, expect, it, vi } from 'vitest'
import {
  createRuntimeSettings,
  parseChoiceInput,
  type RuntimeSettingsDeps
} from './runtimeSettings'

const HOME = '/home/dev'
const CONFIG = `${HOME}/.solus/config.json`

function fakeDeps(initial?: string): RuntimeSettingsDeps & { files: Map<string, string> } {
  const files = new Map<string, string>()
  if (initial !== undefined) files.set(CONFIG, initial)
  return {
    files,
    homedir: () => HOME,
    readFile: (path) => {
      const v = files.get(path)
      if (v === undefined) throw new Error('ENOENT')
      return v
    },
    writeFile: (path, content) => void files.set(path, content),
    replaceFile: (from, to) => {
      files.set(to, files.get(from) as string)
      files.delete(from)
    },
    mkdir: vi.fn(),
    chmod: vi.fn(),
    remove: (path) => void files.delete(path),
    tempSuffix: () => 'abc',
    warn: vi.fn()
  }
}

const doc = (deps: { files: Map<string, string> }): Record<string, unknown> =>
  JSON.parse(deps.files.get(CONFIG) as string)

describe('read', () => {
  it('a missing file or key reads as auto and writable', () => {
    expect(createRuntimeSettings(fakeDeps()).read()).toEqual({
      mode: 'auto',
      path: null,
      writable: true
    })
    expect(
      createRuntimeSettings(fakeDeps(JSON.stringify({ schema_version: 1, sol: {} }))).read()
    ).toEqual({ mode: 'auto', path: null, writable: true })
  })

  it('reads a stored path choice', () => {
    const deps = fakeDeps(
      JSON.stringify({
        schema_version: 1,
        mcp_runtime: { schema_version: 1, python: { mode: 'path', path: '/usr/bin/python3.12' } }
      })
    )
    expect(createRuntimeSettings(deps).read()).toEqual({
      mode: 'path',
      path: '/usr/bin/python3.12',
      writable: true
    })
  })

  it.each([
    ['unknown field', { schema_version: 1, python: { mode: 'auto' }, extra: 1 }],
    ['relative path', { schema_version: 1, python: { mode: 'path', path: 'python3' } }],
    ['path on managed', { schema_version: 1, python: { mode: 'managed', path: '/x' } }],
    ['bad mode', { schema_version: 1, python: { mode: 'system' } }]
  ])('a malformed mcp_runtime (%s) falls back to auto', (_l, runtime) => {
    const deps = fakeDeps(JSON.stringify({ schema_version: 1, mcp_runtime: runtime }))
    expect(createRuntimeSettings(deps).read()).toMatchObject({ mode: 'auto', writable: true })
  })

  it('a newer mcp_runtime.schema_version is read-only', () => {
    const deps = fakeDeps(
      JSON.stringify({
        schema_version: 1,
        mcp_runtime: { schema_version: 2, python: { mode: 'x' } }
      })
    )
    expect(createRuntimeSettings(deps).read()).toMatchObject({ mode: 'auto', writable: false })
  })

  it('a newer file schema_version is read-only', () => {
    const deps = fakeDeps(JSON.stringify({ schema_version: 2 }))
    expect(createRuntimeSettings(deps).read().writable).toBe(false)
  })
})

describe('write', () => {
  it('round-trips while keeping sol and unknown keys verbatim', () => {
    const sol = { screenIntelligence: true, hotkeys: false, drive: true }
    const deps = fakeDeps(JSON.stringify({ schema_version: 1, sol, future_key: { a: [1] } }))
    const settings = createRuntimeSettings(deps)
    expect(settings.write({ mode: 'path', path: '/opt/homebrew/bin/python3.12' })).toBe(true)
    expect(doc(deps)).toEqual({
      schema_version: 1,
      sol,
      future_key: { a: [1] },
      mcp_runtime: {
        schema_version: 1,
        python: { mode: 'path', path: '/opt/homebrew/bin/python3.12' }
      }
    })
    expect(settings.read()).toEqual({
      mode: 'path',
      path: '/opt/homebrew/bin/python3.12',
      writable: true
    })
  })

  it('re-reads the file at write time, so a concurrent sol write is not lost', () => {
    const deps = fakeDeps(JSON.stringify({ schema_version: 1 }))
    const settings = createRuntimeSettings(deps)
    deps.files.set(CONFIG, JSON.stringify({ schema_version: 1, sol: { drive: true } }))
    settings.write({ mode: 'managed', path: null })
    expect(doc(deps)).toMatchObject({
      sol: { drive: true },
      mcp_runtime: { python: { mode: 'managed' } }
    })
    expect((doc(deps).mcp_runtime as { python: object }).python).toEqual({ mode: 'managed' })
  })

  it('writes atomically through a temp file and creates ~/.solus 0700', () => {
    const deps = fakeDeps()
    createRuntimeSettings(deps).write({ mode: 'auto', path: null })
    expect(deps.mkdir).toHaveBeenCalledWith(`${HOME}/.solus`, 0o700)
    expect([...deps.files.keys()]).toEqual([CONFIG])
  })

  it('leaves a newer file untouched', () => {
    const raw = JSON.stringify({ schema_version: 3, sol: {} })
    const deps = fakeDeps(raw)
    expect(createRuntimeSettings(deps).write({ mode: 'managed', path: null })).toBe(false)
    expect(deps.files.get(CONFIG)).toBe(raw)
  })

  it('leaves a newer mcp_runtime untouched', () => {
    const raw = JSON.stringify({ schema_version: 1, mcp_runtime: { schema_version: 2 } })
    const deps = fakeDeps(raw)
    expect(createRuntimeSettings(deps).write({ mode: 'managed', path: null })).toBe(false)
    expect(deps.files.get(CONFIG)).toBe(raw)
  })

  it('replaces a corrupt file with a valid one (same as solSettings)', () => {
    const deps = fakeDeps('{not json')
    expect(createRuntimeSettings(deps).write({ mode: 'auto', path: null })).toBe(true)
    expect(doc(deps)).toEqual({
      schema_version: 1,
      mcp_runtime: { schema_version: 1, python: { mode: 'auto' } }
    })
  })

  it('reports a failed write without throwing', () => {
    const deps = fakeDeps()
    deps.writeFile = () => {
      throw new Error('EACCES')
    }
    expect(createRuntimeSettings(deps).write({ mode: 'auto', path: null })).toBe(false)
    expect(deps.warn).toHaveBeenCalled()
  })
})

describe('parseChoiceInput', () => {
  it('accepts the three modes', () => {
    expect(parseChoiceInput({ mode: 'auto' })).toEqual({ mode: 'auto', path: null })
    expect(parseChoiceInput({ mode: 'managed' })).toEqual({ mode: 'managed', path: null })
    expect(parseChoiceInput({ mode: 'path', path: 'C:\\Python312\\python.exe' })).toEqual({
      mode: 'path',
      path: 'C:\\Python312\\python.exe'
    })
  })

  it('mode path without a path asks for the picker', () => {
    expect(parseChoiceInput({ mode: 'path' })).toEqual({ mode: 'path', path: null })
  })

  it.each([
    null,
    'auto',
    { mode: 'system' },
    { mode: 'path', path: 'python3' },
    { mode: 'path', path: './python' },
    { mode: 'path', path: `/${'a'.repeat(4096)}` },
    { mode: 'path', path: 42 },
    { mode: 'managed', path: '/x' },
    { mode: 'auto', extra: true }
  ])('refuses %j', (input) => {
    expect(parseChoiceInput(input)).toBeNull()
  })
})
