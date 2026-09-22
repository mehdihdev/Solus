// The hook decides WHICH configure step runs, from the connector's config
// fields. That decision is the thing most likely to regress into a provider-id
// check, so it is asserted directly here.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useOAuthConnect } from './useOAuthConnect'
import { useOnboardingStore } from './onboardingStore'
import * as oauthConnect from './oauthConnect'
import * as bridgeModule from '../../lib/desktopBridge'
import type { SelectableItem } from '../../lib/api/resources'

vi.mock('./oauthConnect', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./oauthConnect')>()
  return { ...actual, runOAuthConnect: vi.fn() }
})

// The selection step calls the real API singleton; stub the one call it makes.
vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    listSelectable: vi.fn(async () => [
      { id: 'a/one', name: 'a/one', config: { repo: 'a/one', branch: 'main' } },
      { id: 'a/two', name: 'a/two', config: { repo: 'a/two', branch: 'dev' } }
    ])
  }
})

const mockedRun = vi.mocked(oauthConnect.runOAuthConnect)

const REPO: SelectableItem = {
  id: 'a/one',
  name: 'a/one',
  config: { repo: 'a/one', branch: 'main' }
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
  mockedRun.mockResolvedValue({ ok: true })
})

afterEach(() => vi.restoreAllMocks())

describe('useOAuthConnect', () => {
  registerOAuthDispatchTests()

  registerOAuthInputResolutionTests()

  registerOAuthCancellationTests()

  registerOAuthAttemptIsolationTests()

  registerOAuthProgressTests()
})

function registerOAuthDispatchTests(): void {
  it('starts the orchestration with the provider and the bridge redirect uri', async () => {
    withBridge()
    const { result } = renderHook(() => useOAuthConnect())

    await act(async () => {
      await result.current.start('p1', 'onshape', {
        displayName: 'Onshape',
        configFields: ['document_id']
      })
    })

    expect(mockedRun).toHaveBeenCalledTimes(1)
    const [, projectId, provider, options] = mockedRun.mock.calls[0]
    expect(projectId).toBe('p1')
    expect(provider).toBe('onshape')
    expect(options).toEqual({ redirectUri: 'http://127.0.0.1:9/cb', displayName: 'Onshape' })
  })

  it('passes an empty redirect uri when no bridge is present', async () => {
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(null)
    const { result } = renderHook(() => useOAuthConnect())
    await act(async () => {
      await result.current.start('p1', 'github', { configFields: ['repo'] })
    })
    expect(mockedRun.mock.calls[0][3]).toEqual({ redirectUri: '', displayName: undefined })
  })

  // The selection rule: what the CONNECTOR declares decides, provider id never.
  it('chooses the picker for any provider that declares a selection', async () => {
    withBridge()
    const { result } = renderHook(() => useOAuthConnect())

    let captured: oauthConnect.ConfigureStep | undefined
    mockedRun.mockImplementation(async (deps) => {
      captured = deps.configure
      return { ok: true }
    })

    // A provider the app has never heard of, but one that declares a selection.
    await act(async () => {
      await result.current.start('p1', 'someFutureHost', {
        selection: { mode: 'single', config_key: 'repo', label: 'repository' }
      })
    })

    const outcome = captured!({ projectId: 'p1', sourceId: 's1', provider: 'someFutureHost' })
    // Let discovery settle so the picker registers its resolver.
    await act(async () => undefined)
    // The selection step surfaces a picker through the store rather than a form.
    act(() => {
      result.current.select([REPO])
    })
    await expect(outcome).resolves.toEqual({
      config: { repo: 'a/one', branch: 'main' },
      label: 'a/one'
    })
  })
}

function registerOAuthInputResolutionTests(): void {
  it('chooses the generic fields step for a provider that declares no selection', async () => {
    withBridge()
    const { result } = renderHook(() => useOAuthConnect())

    let captured: oauthConnect.ConfigureStep | undefined
    mockedRun.mockImplementation(async (deps) => {
      captured = deps.configure
      return { ok: true }
    })

    await act(async () => {
      await result.current.start('p1', 'someFutureCad', {
        configFields: ['document_id', 'element_id']
      })
    })

    const outcome = captured!({ projectId: 'p1', sourceId: 's1', provider: 'someFutureCad' })
    await act(async () => {
      result.current.submitConfig({ document_id: 'd1', element_id: 'e1' })
    })
    await expect(outcome).resolves.toEqual({ config: { document_id: 'd1', element_id: 'e1' } })
  })

  it('returns the orchestration result so callers can clean up after a cancel', async () => {
    withBridge()
    mockedRun.mockResolvedValue({ ok: false, error: 'Nothing selected.', sourceId: 's9' })
    const { result } = renderHook(() => useOAuthConnect())
    let settled: oauthConnect.OAuthConnectResult | undefined
    await act(async () => {
      settled = await result.current.start('p1', 'github', { configFields: ['repo'] })
    })
    expect(settled).toEqual({ ok: false, error: 'Nothing selected.', sourceId: 's9' })
  })

  it('cancel resolves a pending in-wizard input with null', async () => {
    withBridge()
    const { result } = renderHook(() => useOAuthConnect())

    let captured: oauthConnect.ConfigureStep | undefined
    mockedRun.mockImplementation(async (deps) => {
      captured = deps.configure
      return { ok: true }
    })
    await act(async () => {
      await result.current.start('p1', 'someFutureCad', { configFields: ['document_id'] })
    })

    const outcome = captured!({ projectId: 'p1', sourceId: 's1', provider: 'someFutureCad' })
    await act(async () => undefined) // let the form register its resolver
    act(() => result.current.cancel())
    await expect(outcome).resolves.toEqual({ error: 'Configuration cancelled.' })
  })
}

function registerOAuthCancellationTests(): void {
  it('after cancel, a LATER input request resolves null immediately instead of parking forever', async () => {
    withBridge()
    const { result } = renderHook(() => useOAuthConnect())

    let captured: oauthConnect.ConfigureStep | undefined
    mockedRun.mockImplementation(async (deps) => {
      captured = deps.configure
      return { ok: true }
    })
    await act(async () => {
      await result.current.start('p1', 'someFutureCad', { configFields: ['document_id'] })
    })

    // Cancel BEFORE the flow reaches its configure step (e.g. user closed the
    // wizard while the browser OAuth handshake was still in flight).
    act(() => result.current.cancel())
    const outcome = captured!({ projectId: 'p1', sourceId: 's1', provider: 'someFutureCad' })
    await expect(outcome).resolves.toEqual({ error: 'Configuration cancelled.' })
  })

  it('cancel aborts the browser handshake so a parked flow settles now', async () => {
    withBridge()
    const { result } = renderHook(() => useOAuthConnect())
    await act(async () => {
      await result.current.start('p1', 'github', { configFields: ['repo'] })
    })
    act(() => result.current.cancel())
    expect(cancelOAuth).toHaveBeenCalledTimes(1)
  })

  it('a cancelled attempt goes quiet: its progress no longer reaches the store', async () => {
    withBridge()
    let emit: ((state: import('./onboardingStore').ConnectionState) => void) | undefined
    mockedRun.mockImplementation(
      (deps) =>
        new Promise((resolve) => {
          emit = deps.onProgress
          deps.onProgress({ phase: 'busy', stage: 'authorize', label: 'Authorizing…' })
          setTimeout(() => resolve({ ok: false, error: 'x' }), 0)
        })
    )
    const { result } = renderHook(() => useOAuthConnect())
    act(() => {
      void result.current.start('p1', 'github', { configFields: ['repo'] })
    })
    await act(async () => undefined)
    expect(useOnboardingStore.getState().connections.github?.phase).toBe('busy')

    act(() => result.current.cancel())
    useOnboardingStore.getState().clearConnection('github')
    // The abandoned flow keeps emitting — nothing may reach the store now.
    act(() => emit?.({ phase: 'busy', stage: 'link', label: 'Linking…' }))
    expect(useOnboardingStore.getState().connections.github).toBeUndefined()
  })
}

function registerOAuthAttemptIsolationTests(): void {
  it("a superseded attempt's input request resolves null instead of stealing the new attempt's resolver", async () => {
    withBridge()
    const { result } = renderHook(() => useOAuthConnect())

    const captured: oauthConnect.ConfigureStep[] = []
    mockedRun.mockImplementation(async (deps) => {
      captured.push(deps.configure)
      return { ok: true }
    })
    await act(async () => {
      await result.current.start('p1', 'someFutureCad', { configFields: ['document_id'] })
    })
    await act(async () => {
      await result.current.start('p1', 'someFutureCad', { configFields: ['document_id'] })
    })

    // The OLD attempt's configure step arrives late: it must settle null-cancelled.
    const stale = captured[0]({ projectId: 'p1', sourceId: 's1', provider: 'someFutureCad' })
    await expect(stale).resolves.toEqual({ error: 'Configuration cancelled.' })

    // The NEW attempt still awaits input normally.
    const live = captured[1]({ projectId: 'p1', sourceId: 's2', provider: 'someFutureCad' })
    await act(async () => {
      result.current.submitConfig({ document_id: 'd9' })
    })
    await expect(live).resolves.toEqual({ config: { document_id: 'd9' } })
  })

  it('a fresh start clears the cancelled latch from a previous attempt', async () => {
    withBridge()
    const { result } = renderHook(() => useOAuthConnect())

    let captured: oauthConnect.ConfigureStep | undefined
    mockedRun.mockImplementation(async (deps) => {
      captured = deps.configure
      return { ok: true }
    })
    await act(async () => {
      await result.current.start('p1', 'someFutureCad', { configFields: ['document_id'] })
    })
    act(() => result.current.cancel())

    // Retry: the new attempt must await input normally again.
    await act(async () => {
      await result.current.start('p1', 'someFutureCad', { configFields: ['document_id'] })
    })
    const outcome = captured!({ projectId: 'p1', sourceId: 's1', provider: 'someFutureCad' })
    await act(async () => {
      result.current.submitConfig({ document_id: 'd2' })
    })
    await expect(outcome).resolves.toEqual({ config: { document_id: 'd2' } })
  })
}

function registerOAuthProgressTests(): void {
  it('routes progress into the onboarding store under the provider key', async () => {
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(null)
    mockedRun.mockImplementation(async (deps) => {
      deps.onProgress({ phase: 'done', sourceId: 's1', result: 'Connected — 5 entities indexed' })
      return { ok: true }
    })
    const { result } = renderHook(() => useOAuthConnect())
    await act(async () => {
      await result.current.start('p1', 'onshape', { configFields: ['document_id'] })
    })
    expect(useOnboardingStore.getState().connections.onshape).toEqual({
      phase: 'done',
      sourceId: 's1',
      result: 'Connected — 5 entities indexed'
    })
  })
}
