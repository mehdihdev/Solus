// @vitest-environment node
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  rmSync,
  statSync,
  symlinkSync,
  readdirSync
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { HARDWARE_LOCAL_STATE_MAX_BYTES } from '@solus/shared-types'
import { HardwareLocalStore } from './hardwareLocalState'

const PROJECT = '00000000-0000-4000-8000-000000000001'
const ACCOUNT = '00000000-0000-4000-8000-000000000002'
const OTHER = '00000000-0000-4000-8000-000000000003'
const REF = '00000000-0000-4000-8000-000000000004'
const source = { path: '/workspace/calibration.json', contentSha256: 'a'.repeat(64) }
const roots: string[] = []
function setup() {
  const home = mkdtempSync(join(tmpdir(), 'solus-hardware-state-'))
  roots.push(home)
  const store = new HardwareLocalStore(home)
  const directory = join(home, '.solus', 'projects', PROJECT)
  return { home, store, directory, path: join(directory, 'hardware.json') }
}
afterEach(() => roots.splice(0).forEach((root) => rmSync(root, { recursive: true, force: true })))

describe('HardwareLocalStore', () => {
  registerHardwareStatePersistenceTests()
  registerHardwareStateIntegrityTests()
  registerHardwareStateLimitsTests()
})

function registerHardwareStatePersistenceTests(): void {
  it('treats absence as empty without creating any private files on read', () => {
    const { store, home } = setup()
    expect(store.read(PROJECT)).toEqual({
      status: 'ready',
      state: { schema_version: 1, accounts: {} }
    })
    expect(readdirSync(home)).toEqual([])
  })

  it('atomically saves private state with 0600 files and 0700 directories', () => {
    const { store, home, directory, path } = setup()
    expect(
      store.updateAccount(PROJECT, ACCOUNT, () => ({ sources: { [REF]: source }, bindings: {} }))
    ).toEqual({ ok: true })
    expect(JSON.parse(readFileSync(path, 'utf8')).accounts[ACCOUNT].sources[REF]).toEqual(source)
    for (const dir of [join(home, '.solus'), join(home, '.solus', 'projects'), directory]) {
      expect(statSync(dir).mode & 0o777).toBe(0o700)
    }
    expect(statSync(path).mode & 0o777).toBe(0o600)
    expect(readdirSync(directory)).toEqual(['hardware.json'])
  })

  it('preserves other accounts, source records and binding hints across updates', () => {
    const { store } = setup()
    store.updateAccount(PROJECT, ACCOUNT, () => ({
      sources: { [REF]: source },
      bindings: { [REF]: { lastSeenPath: '/dev/example' } }
    }))
    store.updateAccount(PROJECT, OTHER, () => ({ sources: {}, bindings: {} }))
    store.updateAccount(PROJECT, ACCOUNT, (account) => ({
      ...account,
      sources: { ...account.sources, [OTHER]: source }
    }))
    const result = store.read(PROJECT)
    expect(result.status).toBe('ready')
    if (result.status !== 'ready') throw new Error('missing state')
    expect(Object.keys(result.state.accounts)).toEqual([ACCOUNT, OTHER])
    expect(Object.keys(result.state.accounts[ACCOUNT].sources)).toEqual([REF, OTHER])
    expect(result.state.accounts[ACCOUNT].bindings[REF]).toEqual({ lastSeenPath: '/dev/example' })
  })

  it.each(['../other', '', '/absolute', 'constructor', 'not-a-uuid'])(
    'rejects unsafe project/account identifiers: %s',
    (id) => {
      const { store, home } = setup()
      expect(store.read(id).status).toBe('invalid')
      expect(store.updateAccount(PROJECT, id, () => ({ sources: {}, bindings: {} }))).toEqual({
        ok: false,
        reason: 'invalid'
      })
      expect(readdirSync(home)).toEqual([])
    }
  )
}

function registerHardwareStateIntegrityTests(): void {
  it.each([
    ['{not-json', 'invalid'],
    [JSON.stringify({ schema_version: 2, future: true }), 'newer'],
    [' '.repeat(HARDWARE_LOCAL_STATE_MAX_BYTES + 1), 'invalid']
  ])('reports invalid/newer state without overwriting it', (raw, status) => {
    const { store, directory, path } = setup()
    mkdirSync(directory, { recursive: true })
    writeFileSync(path, raw)
    expect(store.read(PROJECT).status).toBe(status)
    expect(store.updateAccount(PROJECT, ACCOUNT, () => ({ sources: {}, bindings: {} }))).toEqual({
      ok: false,
      reason: status
    })
    expect(readFileSync(path, 'utf8')).toBe(raw)
  })

  it('refuses a planted symlink at the state file', () => {
    const { store, home, directory, path } = setup()
    mkdirSync(directory, { recursive: true })
    const outside = join(home, 'outside.json')
    writeFileSync(outside, '{"schema_version":1,"accounts":{}}')
    symlinkSync(outside, path)
    expect(store.read(PROJECT).status).toBe('invalid')
    expect(store.updateAccount(PROJECT, ACCOUNT, () => ({ sources: {}, bindings: {} }))).toEqual({
      ok: false,
      reason: 'invalid'
    })
    expect(readFileSync(outside, 'utf8')).toBe('{"schema_version":1,"accounts":{}}')
  })

  it('refuses symlinked parent directories instead of following them', () => {
    const { store, home } = setup()
    const outside = join(home, 'outside')
    mkdirSync(outside)
    symlinkSync(outside, join(home, '.solus'))
    expect(store.read(PROJECT).status).toBe('invalid')
    expect(store.updateAccount(PROJECT, ACCOUNT, () => ({ sources: {}, bindings: {} }))).toEqual({
      ok: false,
      reason: 'invalid'
    })
    expect(readdirSync(outside)).toEqual([])
  })

  it('removes its temporary file if state changes before atomic replacement', () => {
    const { store, directory, path } = setup()
    store.updateAccount(PROJECT, ACCOUNT, () => ({ sources: {}, bindings: {} }))
    const result = store.updateAccount(PROJECT, ACCOUNT, (account) => {
      writeFileSync(path, 'changed by another writer')
      return account
    })
    expect(result).toEqual({ ok: false, reason: 'invalid' })
    expect(readdirSync(directory)).toEqual(['hardware.json'])
    expect(readFileSync(path, 'utf8')).toBe('changed by another writer')
  })
}

function registerHardwareStateLimitsTests(): void {
  it('validates account/map limits before changing existing state', () => {
    const { store, path } = setup()
    store.updateAccount(PROJECT, ACCOUNT, () => ({ sources: {}, bindings: {} }))
    const before = readFileSync(path, 'utf8')
    const sources = Object.fromEntries(
      Array.from({ length: 257 }, (_, index) => [
        `00000000-0000-4000-8000-${index.toString(16).padStart(12, '0')}`,
        source
      ])
    )
    expect(store.updateAccount(PROJECT, ACCOUNT, () => ({ sources, bindings: {} }))).toEqual({
      ok: false,
      reason: 'invalid'
    })
    expect(readFileSync(path, 'utf8')).toBe(before)
  })
}
