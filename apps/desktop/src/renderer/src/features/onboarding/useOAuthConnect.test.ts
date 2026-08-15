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
  mockedRun.mockResolvedValue({ ok: true })
})

afterEach(() => vi.restoreAllMocks())

describe('useOAuthConnect', () => {
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
})
