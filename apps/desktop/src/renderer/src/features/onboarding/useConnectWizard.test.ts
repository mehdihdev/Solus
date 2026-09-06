// The wizard's surface glue: open/begin/pickFile/close for the active catalog
// entry, shared by the Sources page and onboarding. Close mid-flight CANCELS
// the attempt (SOLUSDEV-165): the tile state is forgotten immediately and the
// abandoned flow settles quietly. Cancel NEVER deletes a source — for
// multi-selection connectors the backend reuses the existing connected source,
// so `result.sourceId` can name live, populated graph data (security review
// C1). A flow that completed successfully despite the cancel keeps its source
// and is reported: real work is never thrown away silently.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useConnectWizard, NOT_LINKED_ERROR } from './useConnectWizard'
import { EMPTY_EXPORT_ERROR, MAX_EXPORT_BYTES, OVERSIZE_EXPORT_ERROR } from './edaConnect'
import { useOnboardingStore } from './onboardingStore'
import * as oauthConnect from './oauthConnect'
import * as accountConnect from './accountConnect'
import * as edaConnect from './edaConnect'
import * as resources from '../../lib/api/resources'
import * as bridgeModule from '../../lib/desktopBridge'
import type { CatalogEntry } from './integrationCatalog'

vi.mock('./oauthConnect', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./oauthConnect')>()
  return { ...actual, runOAuthConnect: vi.fn() }
})
vi.mock('./accountConnect', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./accountConnect')>()
  return { ...actual, runAccountConnect: vi.fn() }
})
vi.mock('./edaConnect', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./edaConnect')>()
  return { ...actual, runEdaConnect: vi.fn() }
})
vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    disconnectSource: vi.fn(async () => ({ id: 's1', retained_entities: false }))
  }
})

const mockedOAuth = vi.mocked(oauthConnect.runOAuthConnect)
const mockedAccount = vi.mocked(accountConnect.runAccountConnect)
const mockedEda = vi.mocked(edaConnect.runEdaConnect)

const LINKED_GITHUB: resources.Connection = {
  id: 'c1',
  provider: 'github',
  status: 'connected',
  account_login: 'octocat',
  access: null,
  needs_reauth: null,
  last_error: null,
  health: 'healthy',
  projects: [],
  created_at: '',
  updated_at: ''
}
const mockedDisconnect = vi.mocked(resources.disconnectSource)

const GITHUB: CatalogEntry = {
  id: 'github',
  name: 'GitHub',
  kind: 'Code',
  mark: 'GH',
  mode: 'oauth',
  configFields: ['repo', 'branch'],
  selection: { mode: 'single', config_key: 'repo', label: 'repository' },
  accessModes: null,
  hosted: null
}

const KICAD: CatalogEntry = {
  id: 'kicad',
  name: 'KiCad',
  kind: 'PCB',
  mark: 'Ki',
  mode: 'export-file',
  configFields: ['export'],
  selection: null,
  accessModes: null,
  hosted: null
}

const cancelOAuth = vi.fn(async () => true)

function withBridge(): void {
  vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue({
    getRedirectUrl: vi.fn(async () => 'http://127.0.0.1:9/cb?solus_cb=x'),
    awaitGithub: vi.fn(async () => ({ code: 'cd' })),
    getConnectorRedirectUrl: vi.fn(async () => 'http://127.0.0.1:9/cb'),
    awaitOAuth: vi.fn(async () => ({ code: 'cd' })),
    cancelOAuth
  })
}

beforeEach(() => {
  useOnboardingStore.getState().reset()
  vi.clearAllMocks()
  mockedOAuth.mockResolvedValue({ ok: true, sourceId: 's1' })
  mockedEda.mockResolvedValue({ ok: true, sourceId: 's2' })
})

afterEach(() => vi.restoreAllMocks())

/** Park runOAuthConnect and hand the test its resolve. */
function parkOAuth(firstProgress?: import('./onboardingStore').ConnectionState): {
  settle: (r: oauthConnect.OAuthConnectResult) => void
} {
  const parked = { settle: (() => undefined) as (r: oauthConnect.OAuthConnectResult) => void }
  mockedOAuth.mockImplementation(
    (deps) =>
      new Promise((resolve) => {
        if (firstProgress) deps.onProgress(firstProgress)
        parked.settle = resolve
      })
  )
  return parked
}

describe('useConnectWizard', () => {
  it('open exposes the active entry; close forgets it', () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(GITHUB))
    expect(result.current.active).toEqual(GITHUB)
    act(() => result.current.close())
    expect(result.current.active).toBeNull()
  })

  it('begin without a linked project fails honestly and never starts a flow', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: null }))
    act(() => result.current.open(GITHUB))
    await act(async () => result.current.begin())
    expect(mockedOAuth).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.github).toEqual({
      phase: 'error',
      error: NOT_LINKED_ERROR
    })
  })

  it('begin without the desktop bridge fails honestly for an OAuth connector', async () => {
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(null)
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(GITHUB))
    await act(async () => result.current.begin())
    expect(mockedOAuth).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.github?.phase).toBe('error')
  })

  it('reuses a CONNECTED linked account for the entry (SOLUSDEV-241)', async () => {
    withBridge()
    const { result } = renderHook(() =>
      useConnectWizard({ projectId: 'p1', linkedConnections: [LINKED_GITHUB] })
    )
    act(() => result.current.open(GITHUB))
    expect(result.current.linkedAccount).toEqual(LINKED_GITHUB)
    await act(async () => result.current.begin())
    expect(mockedOAuth.mock.calls[0][3]).toMatchObject({
      linkedConnection: { id: 'c1', login: 'octocat' }
    })
  })

  it('ignores a linked account that is not connected', async () => {
    withBridge()
    const errored = { ...LINKED_GITHUB, status: 'error' as const }
    const { result } = renderHook(() =>
      useConnectWizard({ projectId: 'p1', linkedConnections: [errored] })
    )
    act(() => result.current.open(GITHUB))
    expect(result.current.linkedAccount).toBeNull()
    await act(async () => result.current.begin())
    expect(mockedOAuth.mock.calls[0][3]).not.toHaveProperty('linkedConnection')
  })

  it('account scope binds the account with no project at all', async () => {
    withBridge()
    mockedAccount.mockResolvedValue({ ok: true, connectionId: 'c1', result: 'Connected as x' })
    const onConnected = vi.fn()
    const { result } = renderHook(() =>
      useConnectWizard({ projectId: null, scope: 'account', onConnected })
    )
    act(() => result.current.open(GITHUB))
    expect(result.current.linkedAccount).toBeNull()
    await act(async () => result.current.begin())
    expect(mockedAccount).toHaveBeenCalledTimes(1)
    expect(mockedAccount.mock.calls[0][1]).toBe('github')
    expect(mockedOAuth).not.toHaveBeenCalled()
    expect(onConnected).toHaveBeenCalledTimes(1)
  })

  it('begin drives the OAuth flow and reports success through onConnected', async () => {
    withBridge()
    const onConnected = vi.fn()
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1', onConnected }))
    act(() => result.current.open(GITHUB))
    await act(async () => result.current.begin())
    expect(mockedOAuth).toHaveBeenCalledTimes(1)
    expect(mockedOAuth.mock.calls[0][1]).toBe('p1')
    expect(mockedOAuth.mock.calls[0][2]).toBe('github')
    expect(onConnected).toHaveBeenCalledTimes(1)
  })

  it('pickFile reads the file and drives the committed-export flow', async () => {
    const onConnected = vi.fn()
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1', onConnected }))
    act(() => result.current.open(KICAD))
    await act(async () => result.current.pickFile(new File(['<x/>'], 'a.xml')))
    expect(mockedEda).toHaveBeenCalledTimes(1)
    expect(mockedEda.mock.calls[0][2]).toBe('kicad')
    expect(mockedEda.mock.calls[0][3]).toEqual({ fileName: 'a.xml', content: '<x/>' })
    expect(onConnected).toHaveBeenCalledTimes(1)
  })

  it('rejects an empty pick without reading it and without starting a flow', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    const file = new File([], 'empty.xml')
    const text = vi.spyOn(file, 'text')
    await act(async () => result.current.pickFile(file))
    expect(text).not.toHaveBeenCalled()
    expect(mockedEda).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.kicad).toEqual({
      phase: 'error',
      error: EMPTY_EXPORT_ERROR
    })
  })

  it('rejects an oversized pick by SIZE, before file.text() can hang the renderer', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    const file = new File(['x'], 'huge.xml')
    Object.defineProperty(file, 'size', { value: MAX_EXPORT_BYTES + 1 })
    const text = vi.spyOn(file, 'text')
    await act(async () => result.current.pickFile(file))
    expect(text).not.toHaveBeenCalled()
    expect(mockedEda).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.kicad).toEqual({
      phase: 'error',
      error: OVERSIZE_EXPORT_ERROR
    })
  })

  it('close DURING the file read cancels: no source is created for the abandoned pick', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    const file = new File(['<x/>'], 'a.xml')
    let finishRead: (content: string) => void = () => undefined
    vi.spyOn(file, 'text').mockImplementation(() => new Promise((r) => (finishRead = r)))

    act(() => {
      void result.current.pickFile(file)
    })
    act(() => result.current.close())
    await act(async () => finishRead('<x/>'))

    expect(mockedEda).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.kicad).toBeUndefined()
  })

  it('close mid-flight cancels: clears the tile state and NEVER deletes a source', async () => {
    withBridge()
    const onConnected = vi.fn()
    const parked = parkOAuth({ phase: 'busy', stage: 'authorize', label: 'Authorizing…' })
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1', onConnected }))
    act(() => result.current.open(GITHUB))
    act(() => {
      void result.current.begin()
    })
    await act(async () => undefined) // let the hook reach the engine
    expect(useOnboardingStore.getState().connections.github?.phase).toBe('busy')

    act(() => result.current.close())
    expect(result.current.active).toBeNull()
    expect(useOnboardingStore.getState().connections.github).toBeUndefined()
    // The browser handshake is aborted so the flow settles now.
    expect(cancelOAuth).toHaveBeenCalled()

    // The abandoned flow settles as a failure that DID create a source. It is
    // NOT deleted — for reused-source connectors that id can be live graph
    // data, and cancel must never destroy anything (CLAUDE.md §7).
    act(() => parked.settle({ ok: false, error: 'Configuration cancelled.', sourceId: 's7' }))
    await act(async () => undefined)
    expect(mockedDisconnect).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.github).toBeUndefined()
    expect(onConnected).not.toHaveBeenCalled()
  })

  it('close BEFORE the first progress write still cancels the attempt', async () => {
    withBridge()
    const parked = parkOAuth()
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(GITHUB))
    act(() => {
      void result.current.begin()
    })
    // No progress has been written yet — the attempt must still be cancellable.
    act(() => result.current.close())
    expect(cancelOAuth).toHaveBeenCalled()

    act(() => parked.settle({ ok: false, error: 'Connect cancelled.' }))
    await act(async () => undefined)
    expect(useOnboardingStore.getState().connections.github).toBeUndefined()
  })

  it('a cancelled flow that still completed keeps its source — work is not thrown away', async () => {
    withBridge()
    const onConnected = vi.fn()
    const parked = parkOAuth({ phase: 'busy', stage: 'index', label: 'Indexing…' })
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1', onConnected }))
    act(() => result.current.open(GITHUB))
    act(() => {
      void result.current.begin()
    })
    await act(async () => undefined)
    act(() => result.current.close())

    act(() => parked.settle({ ok: true, sourceId: 's8', result: 'Connected — 3 entities indexed' }))
    await waitFor(() => expect(onConnected).toHaveBeenCalledTimes(1))
    expect(mockedDisconnect).not.toHaveBeenCalled()
  })

  it("a stale cancelled attempt cannot clear a NEWER attempt's tile state", async () => {
    withBridge()
    const parked = parkOAuth({ phase: 'busy', stage: 'authorize', label: 'Authorizing…' })
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(GITHUB))
    act(() => {
      void result.current.begin()
    })
    await act(async () => undefined)
    const settleA = parked.settle
    act(() => result.current.close()) // cancel attempt A

    // Retry: attempt B is live and busy.
    const parkedB = parkOAuth({ phase: 'busy', stage: 'authorize', label: 'Authorizing…' })
    act(() => result.current.open(GITHUB))
    act(() => {
      void result.current.begin()
    })
    await act(async () => undefined)
    expect(useOnboardingStore.getState().connections.github?.phase).toBe('busy')

    // A settles late, as a cancelled failure — B's busy tile must survive.
    act(() => settleA({ ok: false, error: 'Configuration cancelled.', sourceId: 's7' }))
    await act(async () => undefined)
    expect(useOnboardingStore.getState().connections.github?.phase).toBe('busy')
    expect(mockedDisconnect).not.toHaveBeenCalled()

    act(() => parkedB.settle({ ok: true, sourceId: 's9' }))
  })

  it('closing on an error keeps the error state so the tile stays retryable', async () => {
    withBridge()
    mockedOAuth.mockImplementation(async (deps) => {
      deps.onProgress({ phase: 'error', error: 'GitHub sign-in was cancelled.' })
      return { ok: false, error: 'GitHub sign-in was cancelled.' }
    })
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(GITHUB))
    await act(async () => result.current.begin())
    act(() => result.current.close())
    expect(useOnboardingStore.getState().connections.github).toEqual({
      phase: 'error',
      error: 'GitHub sign-in was cancelled.'
    })
    expect(cancelOAuth).not.toHaveBeenCalled()
  })
})
