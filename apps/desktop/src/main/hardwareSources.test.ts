// @vitest-environment node
import { createHash } from 'node:crypto'
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  symlinkSync,
  rmSync,
  readFileSync,
  realpathSync
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HardwareLocalStore } from './hardwareLocalState'
import {
  HardwareSources,
  authorizeHardwareScope,
  readHardwareSource,
  MAX_HARDWARE_SOURCE_BYTES
} from './hardwareSources'

const PROJECT = '00000000-0000-4000-8000-000000000001'
const ACCOUNT = '00000000-0000-4000-8000-000000000002'
const OTHER = '00000000-0000-4000-8000-000000000003'
const REF = '00000000-0000-4000-8000-000000000004'
const roots: string[] = []
const digest = (bytes: string): string => createHash('sha256').update(bytes).digest('hex')
function setup(): {
  home: string
  file: string
  store: HardwareLocalStore
  sources: HardwareSources
  deps: {
    store: HardwareLocalStore
    authorize: ReturnType<typeof vi.fn<() => Promise<string | null>>>
    pickFile: ReturnType<typeof vi.fn<() => Promise<string | null>>>
    confirmDigestChange: ReturnType<typeof vi.fn<() => Promise<boolean>>>
    readFile: typeof readHardwareSource
    newId: () => string
  }
} {
  // readHardwareSource refuses any path whose realpath differs from the path
  // given (symlinked-parent guard). macOS's tmpdir is /var → /private/var, so
  // the fixture home must be canonical or every pick fails with relink_required.
  const home = realpathSync(mkdtempSync(join(tmpdir(), 'solus-hardware-sources-')))
  roots.push(home)
  const file = join(home, 'calibration.json')
  writeFileSync(file, '{"joint":1}')
  const store = new HardwareLocalStore(home)
  const deps = {
    store,
    authorize: vi.fn(async () => ACCOUNT as string | null),
    pickFile: vi.fn(async () => file as string | null),
    confirmDigestChange: vi.fn(async () => true),
    readFile: readHardwareSource,
    newId: () => REF
  }
  const sources = new HardwareSources(deps)
  sources.setToken('test-session')
  sources.setProject(PROJECT)
  return { home, file, store, deps, sources }
}
afterEach(() => roots.splice(0).forEach((root) => rmSync(root, { recursive: true, force: true })))

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('HardwareSources authenticated picker', () => {
  registerPickerAuthorizationTests()
  registerPickerScopeAndCancellationTests()
  registerPickerConcurrencyAndRelinkingTests()
  registerPickerDigestAndPersistenceTests()
})

describe('readHardwareSource', () => {
  it('refuses symlink files, non-files, oversized files, unsupported formats and invalid UTF-8', async () => {
    const { home, file } = setup()
    const linked = join(home, 'linked.json')
    symlinkSync(file, linked)
    await expect(readHardwareSource(linked)).rejects.toThrow()
    await expect(readHardwareSource(home)).rejects.toThrow()
    const big = join(home, 'big.json')
    writeFileSync(big, Buffer.alloc(MAX_HARDWARE_SOURCE_BYTES + 1))
    await expect(readHardwareSource(big)).rejects.toThrow()
    const bad = join(home, 'bad.json')
    writeFileSync(bad, Buffer.from([0xff, 0xfe]))
    await expect(readHardwareSource(bad)).rejects.toThrow()
    const executable = join(home, 'run.sh')
    writeFileSync(executable, 'echo bad')
    await expect(readHardwareSource(executable)).rejects.toThrow()
  })

  it('refuses a symlinked parent that changes the selected canonical path', async () => {
    const { home } = setup()
    const target = join(home, 'target')
    mkdirSync(target)
    writeFileSync(join(target, 'config.json'), '{}')
    symlinkSync(target, join(home, 'alias'))
    await expect(readHardwareSource(join(home, 'alias', 'config.json'))).rejects.toThrow()
  })
})

describe('authorizeHardwareScope', () => {
  it('uses configured API identity and project membership, with no redirects', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { id: ACCOUNT } })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { id: PROJECT } })))
    expect(
      await authorizeHardwareScope(
        'test-session',
        PROJECT,
        new AbortController().signal,
        'https://api.example.test/api/v1',
        fetcher
      )
    ).toBe(ACCOUNT)
    expect(fetcher.mock.calls.map((call) => call[0])).toEqual([
      'https://api.example.test/api/v1/users/me',
      `https://api.example.test/api/v1/projects/${PROJECT}`
    ])
    expect(fetcher.mock.calls.every((call) => call[1].redirect === 'error')).toBe(true)
  })

  it('refuses insecure non-loopback APIs, denied membership, mismatched project and oversized identity responses', async () => {
    const signal = new AbortController().signal
    const fetcher = vi.fn()
    expect(
      await authorizeHardwareScope(
        'test-session',
        PROJECT,
        signal,
        'http://remote.example.test/api/v1',
        fetcher
      )
    ).toBe(null)
    expect(fetcher).not.toHaveBeenCalled()
    fetcher
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { id: ACCOUNT } })))
      .mockResolvedValueOnce(new Response('', { status: 403 }))
    expect(
      await authorizeHardwareScope(
        'test-session',
        PROJECT,
        signal,
        'http://127.0.0.1:8000/api/v1',
        fetcher
      )
    ).toBe(null)
    fetcher
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { id: ACCOUNT } })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { id: OTHER } })))
    expect(
      await authorizeHardwareScope(
        'test-session',
        PROJECT,
        signal,
        'https://api.example.test/api/v1',
        fetcher
      )
    ).toBe(null)
    fetcher.mockResolvedValueOnce(new Response(' '.repeat(256 * 1024 + 1)))
    expect(
      await authorizeHardwareScope(
        'test-session',
        PROJECT,
        signal,
        'https://api.example.test/api/v1',
        fetcher
      )
    ).toBe(null)
  })
})

function registerPickerAuthorizationTests(): void {
  it('returns only portable scope/ref/digest/filename from the selected bytes', async () => {
    const { sources, file, store, deps } = setup()
    const result = await sources.pick(true, {})
    expect(result).toEqual({
      ok: true,
      value: {
        projectId: PROJECT,
        accountId: ACCOUNT,
        source: {
          sourceRef: REF,
          contentSha256: digest('{"joint":1}'),
          displayName: 'calibration.json'
        }
      }
    })
    expect(JSON.stringify(result)).not.toContain(file)
    expect(deps.authorize).toHaveBeenCalledWith('test-session', PROJECT, expect.any(AbortSignal))
    const saved = store.read(PROJECT)
    if (saved.status !== 'ready') throw new Error('missing saved state')
    expect(saved.state.accounts[ACCOUNT].sources[REF].path).toBe(file)
  })

  it('refuses hostile senders before auth, dialog or filesystem access', async () => {
    const { sources, deps } = setup()
    expect(await sources.pick(false, {})).toEqual({ ok: false, reason: 'unauthorized' })
    expect(await sources.list(false)).toEqual({ ok: false, reason: 'unauthorized' })
    expect(deps.authorize).not.toHaveBeenCalled()
    expect(deps.pickFile).not.toHaveBeenCalled()
  })

  it('never treats a renderer-named path or account as authority', async () => {
    const { sources, deps } = setup()
    expect(await sources.pick(true, { path: '/private/file.json' })).toEqual({
      ok: false,
      reason: 'invalid'
    })
    expect(await sources.pick(true, { accountId: OTHER })).toEqual({ ok: false, reason: 'invalid' })
    expect(deps.pickFile).not.toHaveBeenCalled()
  })

  it('requires real authenticated project membership', async () => {
    const { sources, deps } = setup()
    deps.authorize.mockResolvedValue(null)
    expect(await sources.pick(true, {})).toEqual({ ok: false, reason: 'unauthorized' })
    expect(deps.pickFile).not.toHaveBeenCalled()
    sources.setToken(null)
    expect(await sources.list(true)).toEqual({ ok: false, reason: 'unauthorized' })
  })
}

function registerPickerScopeAndCancellationTests(): void {
  it('lists only the server-verified account and refuses another account source ref', async () => {
    const { sources, deps, store } = setup()
    store.updateAccount(PROJECT, OTHER, () => ({
      sources: { [REF]: { path: '/elsewhere/config.json', contentSha256: 'a'.repeat(64) } },
      bindings: {}
    }))
    expect(await sources.list(true)).toEqual({
      ok: true,
      value: { projectId: PROJECT, accountId: ACCOUNT, sources: [] }
    })
    expect(await sources.recheck(true, { sourceRef: REF })).toEqual({
      ok: false,
      reason: 'not_found'
    })
    expect(deps.pickFile).not.toHaveBeenCalled()
  })

  it('never leaks a foreign-platform path through a display filename', async () => {
    const { sources, store } = setup()
    store.updateAccount(PROJECT, ACCOUNT, () => ({
      sources: {
        [REF]: { path: 'C:\\private\\calibration.json', contentSha256: 'a'.repeat(64) }
      },
      bindings: {}
    }))
    const result = await sources.list(true)
    expect(result.ok && result.value.sources[0].displayName).toBe('calibration.json')
    expect(JSON.stringify(result)).not.toContain('private')
  })

  it('does not create state when the dialog is cancelled', async () => {
    const { sources, deps, store } = setup()
    deps.pickFile.mockResolvedValue(null)
    expect(await sources.pick(true, {})).toEqual({ ok: false, reason: 'cancelled' })
    expect(store.read(PROJECT)).toEqual({
      status: 'ready',
      state: { schema_version: 1, accounts: {} }
    })
  })

  it('rejects a pending dialog after project A to B to A transitions', async () => {
    const { sources, deps, file, store } = setup()
    const pick = deferred<string | null>()
    deps.pickFile.mockReturnValue(pick.promise)
    const pending = sources.pick(true, {})
    await vi.waitFor(() => expect(deps.pickFile).toHaveBeenCalled())
    sources.setProject(OTHER)
    sources.setProject(PROJECT)
    pick.resolve(file)
    expect(await pending).toEqual({ ok: false, reason: 'stale_scope' })
    expect(store.read(PROJECT)).toEqual({
      status: 'ready',
      state: { schema_version: 1, accounts: {} }
    })
  })
}

function registerPickerConcurrencyAndRelinkingTests(): void {
  it('invalidates pending authorization on signout even after signing in again', async () => {
    const { sources, deps } = setup()
    const auth = deferred<string | null>()
    deps.authorize.mockReturnValue(auth.promise)
    const pending = sources.list(true)
    sources.setToken(null)
    sources.setToken('test-session')
    auth.resolve(ACCOUNT)
    expect(await pending).toEqual({ ok: false, reason: 'stale_scope' })
  })

  it('allows only one native picker at a time', async () => {
    const { sources, deps } = setup()
    const pick = deferred<string | null>()
    deps.pickFile.mockReturnValue(pick.promise)
    const pending = sources.pick(true, {})
    await vi.waitFor(() => expect(deps.pickFile).toHaveBeenCalled())
    expect(await sources.pick(true, {})).toEqual({ ok: false, reason: 'busy' })
    pick.resolve(null)
    await pending
  })

  it('requires concrete digest-change confirmation before replacing an existing ref', async () => {
    const { sources, deps, file, home } = setup()
    await sources.pick(true, {})
    const statePath = join(home, '.solus', 'projects', PROJECT, 'hardware.json')
    const before = readFileSync(statePath, 'utf8')
    writeFileSync(file, '{"joint":2}')
    expect(await sources.recheck(true, { sourceRef: REF })).toEqual({
      ok: false,
      reason: 'source_changed'
    })
    deps.confirmDigestChange.mockResolvedValue(false)
    expect(await sources.pick(true, { sourceRef: REF })).toEqual({ ok: false, reason: 'cancelled' })
    expect(readFileSync(statePath, 'utf8')).toBe(before)
    deps.confirmDigestChange.mockResolvedValue(true)
    const result = await sources.pick(true, { sourceRef: REF })
    expect(result.ok).toBe(true)
    expect(deps.confirmDigestChange).toHaveBeenLastCalledWith({
      displayName: 'calibration.json',
      previousDigest: digest('{"joint":1}'),
      contentSha256: digest('{"joint":2}')
    })
    expect(readFileSync(statePath, 'utf8')).toContain(digest('{"joint":2}'))
  })

  it('explicitly relinks an unknown migrated reference using the native picker', async () => {
    const { sources, deps, store, file } = setup()
    const result = await sources.pick(true, { sourceRef: REF })
    expect(result.ok && result.value.source.sourceRef).toBe(REF)
    expect(deps.pickFile).toHaveBeenCalledOnce()
    const state = store.read(PROJECT)
    expect(state.status === 'ready' && state.state.accounts[ACCOUNT].sources[REF].path).toBe(file)
  })
}

function registerPickerDigestAndPersistenceTests(): void {
  it('reviews changed known bytes when relinking an unknown reference to the same file', async () => {
    const { sources, deps, file } = setup()
    await sources.pick(true, {})
    writeFileSync(file, '{"joint":2}')
    deps.confirmDigestChange.mockResolvedValue(false)
    expect(await sources.pick(true, { sourceRef: OTHER })).toEqual({
      ok: false,
      reason: 'cancelled'
    })
    expect(deps.confirmDigestChange).toHaveBeenCalledOnce()
  })

  it('reuses a selected canonical file reference and reviews changed bytes', async () => {
    const { sources, deps, file, store } = setup()
    await sources.pick(true, {})
    deps.newId = () => OTHER
    const same = await sources.pick(true, {})
    expect(same.ok && same.value.source.sourceRef).toBe(REF)
    writeFileSync(file, '{"joint":3}')
    deps.confirmDigestChange.mockResolvedValue(false)
    expect(await sources.pick(true, {})).toEqual({ ok: false, reason: 'cancelled' })
    const state = store.read(PROJECT)
    expect(state.status === 'ready' && Object.keys(state.state.accounts[ACCOUNT].sources)).toEqual([
      REF
    ])
  })

  it('checks membership again after a dialog before persistence', async () => {
    const { sources, deps, store } = setup()
    deps.authorize.mockResolvedValueOnce(ACCOUNT).mockResolvedValueOnce(null)
    expect(await sources.pick(true, {})).toEqual({ ok: false, reason: 'unauthorized' })
    expect(store.read(PROJECT)).toEqual({
      status: 'ready',
      state: { schema_version: 1, accounts: {} }
    })
  })

  it('reports corrupt state without showing a picker or overwriting it', async () => {
    const { sources, deps, home } = setup()
    const dir = join(home, '.solus', 'projects', PROJECT)
    mkdirSync(dir, { recursive: true })
    writeFileSync(join(dir, 'hardware.json'), 'bad')
    expect(await sources.pick(true, {})).toEqual({ ok: false, reason: 'invalid' })
    expect(deps.pickFile).not.toHaveBeenCalled()
    expect(readFileSync(join(dir, 'hardware.json'), 'utf8')).toBe('bad')
  })
}
