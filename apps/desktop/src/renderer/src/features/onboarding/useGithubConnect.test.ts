import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useGithubConnect } from './useGithubConnect'
import { useOnboardingStore } from './onboardingStore'
import * as githubConnect from './githubConnect'
import * as bridgeModule from '../../lib/desktopBridge'
import type { GithubRepo } from '../../lib/api/resources'

vi.mock('./githubConnect', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./githubConnect')>()
  return { ...actual, runGithubConnect: vi.fn() }
})

const mockedRun = vi.mocked(githubConnect.runGithubConnect)

beforeEach(() => {
  useOnboardingStore.getState().reset()
  vi.clearAllMocks()
  mockedRun.mockResolvedValue({ ok: true })
})

afterEach(() => vi.restoreAllMocks())

describe('useGithubConnect', () => {
  it('starts the orchestration with the bridge redirect uri', async () => {
    const bridge = {
      getRedirectUrl: vi.fn(async () => 'http://127.0.0.1:9/cb'),
      awaitGithub: vi.fn(async () => ({ code: 'cd' }))
    }
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(bridge)

    const { result } = renderHook(() => useGithubConnect())
    await act(async () => {
      await result.current.start('p1')
    })

    expect(mockedRun).toHaveBeenCalledTimes(1)
    const [, projectId, options] = mockedRun.mock.calls[0]
    expect(projectId).toBe('p1')
    expect(options).toEqual({ redirectUri: 'http://127.0.0.1:9/cb' })
  })

  it('passes an empty redirect uri when no bridge is present', async () => {
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(null)
    const { result } = renderHook(() => useGithubConnect())
    await act(async () => {
      await result.current.start('p1')
    })
    expect(mockedRun.mock.calls[0][2]).toEqual({ redirectUri: '' })
  })

  it('resolves the repo picker through chooseRepo', async () => {
    const bridge = {
      getRedirectUrl: vi.fn(async () => 'cb'),
      awaitGithub: vi.fn(async () => ({ code: 'cd' }))
    }
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(bridge)
    const repo: GithubRepo = { full_name: 'a/one', default_branch: 'main', private: false }

    // Capture the onChooseRepo callback the hook passes to the orchestration.
    let captured: ((repos: GithubRepo[]) => Promise<GithubRepo | null>) | undefined
    mockedRun.mockImplementation(async (deps) => {
      captured = deps.onChooseRepo
      return { ok: true }
    })

    const { result } = renderHook(() => useGithubConnect())
    await act(async () => {
      await result.current.start('p1')
    })

    expect(captured).toBeDefined()
    const choicePromise = captured!([repo])
    act(() => {
      result.current.chooseRepo(repo)
    })
    await expect(choicePromise).resolves.toEqual(repo)
  })

  it('routes progress into the onboarding store', async () => {
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(null)
    mockedRun.mockImplementation(async (deps) => {
      deps.onProgress({ phase: 'done', sourceId: 's1', result: 'Connected — 5 entities indexed' })
      return { ok: true }
    })
    const { result } = renderHook(() => useGithubConnect())
    await act(async () => {
      await result.current.start('p1')
    })
    expect(useOnboardingStore.getState().connections.github).toEqual({
      phase: 'done',
      sourceId: 's1',
      result: 'Connected — 5 entities indexed'
    })
  })
})
