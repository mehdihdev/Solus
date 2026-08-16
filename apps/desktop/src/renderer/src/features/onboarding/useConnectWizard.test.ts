// The wizard's surface glue: open/begin/pickFile/close for the active catalog
// entry, shared by the Sources page and onboarding. Close mid-flight CANCELS
// the attempt (SOLUSDEV-165): the connection entry is forgotten immediately,
// and once the flow settles a dangling half-configured source is deleted
// (retain_entities=false — it produced no graph data). A flow that completed
// successfully despite the cancel keeps its source: real work is never thrown
// away silently.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useConnectWizard, NOT_LINKED_ERROR } from './useConnectWizard'
import { useOnboardingStore } from './onboardingStore'
import * as oauthConnect from './oauthConnect'
import * as edaConnect from './edaConnect'
import * as resources from '../../lib/api/resources'
import * as bridgeModule from '../../lib/desktopBridge'
import type { CatalogEntry } from './integrationCatalog'

vi.mock('./oauthConnect', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./oauthConnect')>()
  return { ...actual, runOAuthConnect: vi.fn() }
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
const mockedEda = vi.mocked(edaConnect.runEdaConnect)
const mockedDisconnect = vi.mocked(resources.disconnectSource)

const GITHUB: CatalogEntry = {
  id: 'github',
  name: 'GitHub',
  kind: 'Code',
  mark: 'GH',
  mode: 'oauth',
  configFields: ['repo', 'branch'],
  selection: { mode: 'single', config_key: 'repo', label: 'repository' },
  accessModes: null
}

const KICAD: CatalogEntry = {
  id: 'kicad',
  name: 'KiCad',
  kind: 'PCB',
  mark: 'Ki',
  mode: 'export-file',
  configFields: ['export'],
  selection: null,
  accessModes: null
}

function withBridge(): void {
  vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue({
    getRedirectUrl: vi.fn(async () => 'http://127.0.0.1:9/cb?solus_cb=x'),
    awaitGithub: vi.fn(async () => ({ code: 'cd' })),
    getConnectorRedirectUrl: vi.fn(async () => 'http://127.0.0.1:9/cb'),
    awaitOAuth: vi.fn(async () => ({ code: 'cd' }))
  })
}

beforeEach(() => {
  useOnboardingStore.getState().reset()
  vi.clearAllMocks()
  mockedOAuth.mockResolvedValue({ ok: true, sourceId: 's1' })
  mockedEda.mockResolvedValue({ ok: true, sourceId: 's2' })
})

afterEach(() => vi.restoreAllMocks())

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
    const state = useOnboardingStore.getState().connections.github
    expect(state?.phase).toBe('error')
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

  it('pickFile drives the committed-export flow and reports success', async () => {
    const onConnected = vi.fn()
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1', onConnected }))
    act(() => result.current.open(KICAD))
    await act(async () => result.current.pickFile({ fileName: 'a.xml', content: '<x/>' }))
    expect(mockedEda).toHaveBeenCalledTimes(1)
    expect(mockedEda.mock.calls[0][2]).toBe('kicad')
    expect(onConnected).toHaveBeenCalledTimes(1)
  })

  it('close mid-flight cancels: clears the tile state and deletes the dangling source', async () => {
    withBridge()
    const onConnected = vi.fn()
    let settle: (r: oauthConnect.OAuthConnectResult) => void = () => undefined
    mockedOAuth.mockImplementation(
      (deps) =>
        new Promise((resolve) => {
          deps.onProgress({ phase: 'busy', stage: 'authorize', label: 'Authorizing…' })
          settle = resolve
        })
    )
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1', onConnected }))
    act(() => result.current.open(GITHUB))
    act(() => {
      void result.current.begin()
    })
    // Let the hook reach the engine (it awaits the bridge redirect URL first).
    await act(async () => undefined)
    expect(useOnboardingStore.getState().connections.github?.phase).toBe('busy')

    act(() => result.current.close())
    expect(result.current.active).toBeNull()
    expect(useOnboardingStore.getState().connections.github).toBeUndefined()

    // The abandoned flow settles later with a half-made source: it is deleted,
    // its data too (it has none), and the tile stays clean.
    act(() => settle({ ok: false, error: 'Configuration cancelled.', sourceId: 's7' }))
    await waitFor(() => expect(mockedDisconnect).toHaveBeenCalledTimes(1))
    expect(mockedDisconnect).toHaveBeenCalledWith('p1', 's7', { retainEntities: false })
    expect(useOnboardingStore.getState().connections.github).toBeUndefined()
    expect(onConnected).not.toHaveBeenCalled()
  })

  it('a cancelled flow that still completed keeps its source — work is not thrown away', async () => {
    withBridge()
    const onConnected = vi.fn()
    let settle: (r: oauthConnect.OAuthConnectResult) => void = () => undefined
    mockedOAuth.mockImplementation(
      (deps) =>
        new Promise((resolve) => {
          deps.onProgress({ phase: 'busy', stage: 'index', label: 'Indexing…' })
          settle = resolve
        })
    )
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1', onConnected }))
    act(() => result.current.open(GITHUB))
    act(() => {
      void result.current.begin()
    })
    await act(async () => undefined)
    act(() => result.current.close())

    act(() => settle({ ok: true, sourceId: 's8', result: 'Connected — 3 entities indexed' }))
    await waitFor(() => expect(onConnected).toHaveBeenCalledTimes(1))
    expect(mockedDisconnect).not.toHaveBeenCalled()
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
  })
})
