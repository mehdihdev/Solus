// SOLUSDEV-249 (I2) — the LOCAL FOLDER card's data hook: link carries this
// machine's identity, unlink disconnects the source, and the view polls fast
// while a scan runs, slowly otherwise, and on window focus.
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../lib/api/envelope.types'
import type { Source } from '../../lib/api/resources'
import type { LocalFolderView } from '../../lib/api/resources.localfolder'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { IDLE_POLL_MS, SYNCING_POLL_MS, linkedFolderPresentation } from './localFolder.constants'
import { useLocalFolder, type LocalFolderDeps } from './useLocalFolder'

const MACHINE = { id: '0123456789abcdef0123456789abcdef', name: 'mehdi-mbp' }

const source = (over: Partial<Source> = {}): Source => ({
  id: 's1',
  project_id: 'p1',
  type: 'local',
  name: 'mehdi-mbp',
  status: 'syncing',
  config: {},
  account_login: null,
  last_synced_at: null,
  last_error: null,
  created_at: '',
  updated_at: '',
  ...over
})

const view = (over: Partial<LocalFolderView> = {}): LocalFolderView => ({
  source: source(),
  bridge: { connected: true, tools_installed: { vscode: true } },
  detected: [],
  ...over
})

function fakeDeps(over: Partial<LocalFolderDeps> = {}): LocalFolderDeps {
  return {
    machine: vi.fn(async () => MACHINE),
    linkLocalFolder: vi.fn(async () => ({ source: source(), job_id: 'j1' })),
    getLocalFolder: vi.fn(async () => view()),
    openLocalFolderEntity: vi.fn(async () => ({
      launched: true,
      tool: 'kicad' as const,
      reason: null
    })),
    disconnectSource: vi.fn(async () => ({ id: 's1', retained_entities: true })),
    ...over
  }
}

beforeEach(() => {
  useWorkspaceStore.setState({ linked: true })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useLocalFolder — link / unlink', () => {
  it('links with this machine’s identity and the folder’s basename, then re-reads the view', async () => {
    const deps = fakeDeps()
    const { result } = renderHook(() => useLocalFolder('p1', true, deps))

    // Issued straight after mount — before the identity has settled.
    await act(() => result.current.link('/home/u/code/rover-fw'))

    expect(deps.linkLocalFolder).toHaveBeenCalledWith('p1', {
      machine_id: MACHINE.id,
      machine_name: MACHINE.name,
      folder_name: 'rover-fw'
    })
    expect(result.current.view?.source?.id).toBe('s1')
    expect(deps.getLocalFolder).toHaveBeenCalledWith('p1', MACHINE.id)
  })

  it('disconnects the current local source on unlink and drops the view', async () => {
    const deps = fakeDeps()
    const { result } = renderHook(() => useLocalFolder('p1', true, deps))

    await waitFor(() => expect(result.current.view?.source?.id).toBe('s1'))
    await act(() => result.current.unlink())

    expect(deps.disconnectSource).toHaveBeenCalledWith('p1', 's1', { retainEntities: true })
    expect(result.current.view).toBeNull()
  })

  it('reports a machine without an id and never asks the API for a view', async () => {
    const deps = fakeDeps({ machine: vi.fn(async () => null) })
    const { result } = renderHook(() => useLocalFolder('p1', true, deps))

    await waitFor(() => expect(result.current.machineAvailable).toBe(false))
    await act(() => result.current.link('/home/u/rover-fw'))

    expect(deps.getLocalFolder).not.toHaveBeenCalled()
    expect(deps.linkLocalFolder).not.toHaveBeenCalled()
  })

  it('fetches nothing while no folder is linked', async () => {
    const deps = fakeDeps()
    const { result } = renderHook(() => useLocalFolder('p1', false, deps))
    await waitFor(() => expect(result.current.machineAvailable).toBe(true))
    expect(deps.getLocalFolder).not.toHaveBeenCalled()
    expect(result.current.status).toBe('idle')
  })

  it('goes offline honestly when the view cannot be read', async () => {
    const deps = fakeDeps({ getLocalFolder: vi.fn(async () => Promise.reject(new Error('down'))) })
    const { result } = renderHook(() => useLocalFolder('p1', true, deps))
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(result.current.view).toBeNull()
  })
})

describe('useLocalFolder — open', () => {
  it('opens through the source’s route and returns the tool’s answer', async () => {
    const deps = fakeDeps()
    const { result } = renderHook(() => useLocalFolder('p1', true, deps))
    await waitFor(() => expect(result.current.view?.source?.id).toBe('s1'))

    const answer = await result.current.open('e1', 'kicad')

    expect(deps.openLocalFolderEntity).toHaveBeenCalledWith('p1', 's1', {
      entity_id: 'e1',
      tool: 'kicad'
    })
    expect(answer).toEqual({ launched: true, tool: 'kicad', reason: null })
  })

  it('turns an API refusal into a not-launched answer with its message', async () => {
    const deps = fakeDeps({
      openLocalFolderEntity: vi.fn(async () =>
        Promise.reject(new ApiError(409, 'bridge_offline', 'No companion session'))
      )
    })
    const { result } = renderHook(() => useLocalFolder('p1', true, deps))
    await waitFor(() => expect(result.current.view?.source?.id).toBe('s1'))

    expect(await result.current.open('e1', 'kicad')).toEqual({
      launched: false,
      tool: 'kicad',
      reason: 'No companion session'
    })
  })

  it('answers null when there is no source to open through', async () => {
    const deps = fakeDeps()
    const { result } = renderHook(() => useLocalFolder('p1', false, deps))
    await act(() => Promise.resolve())
    expect(await result.current.open('e1', 'kicad')).toBeNull()
    expect(deps.openLocalFolderEntity).not.toHaveBeenCalled()
  })
})

describe('useLocalFolder — polling', () => {
  it('polls every 3 s while scanning, every 30 s otherwise, and on window focus', async () => {
    vi.useFakeTimers()
    const getLocalFolder = vi.fn(async () => view())
    const deps = fakeDeps({ getLocalFolder })
    const { result, unmount } = renderHook(() => useLocalFolder('p1', true, deps))

    await act(() => vi.advanceTimersByTimeAsync(0))
    expect(getLocalFolder).toHaveBeenCalledTimes(1)
    expect(result.current.view?.source?.status).toBe('syncing')

    await act(() => vi.advanceTimersByTimeAsync(SYNCING_POLL_MS))
    expect(getLocalFolder).toHaveBeenCalledTimes(2)

    getLocalFolder.mockResolvedValue(
      view({ source: source({ status: 'connected', last_synced_at: '2026-09-07T00:00:00Z' }) })
    )
    await act(() => vi.advanceTimersByTimeAsync(SYNCING_POLL_MS))
    expect(getLocalFolder).toHaveBeenCalledTimes(3)
    expect(result.current.view?.source?.status).toBe('connected')

    // Settled: the fast cadence stops …
    await act(() => vi.advanceTimersByTimeAsync(SYNCING_POLL_MS * 2))
    expect(getLocalFolder).toHaveBeenCalledTimes(3)
    // … and the slow one takes over.
    await act(() => vi.advanceTimersByTimeAsync(IDLE_POLL_MS))
    expect(getLocalFolder).toHaveBeenCalledTimes(4)

    await act(async () => {
      window.dispatchEvent(new Event('focus'))
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(getLocalFolder).toHaveBeenCalledTimes(5)

    unmount()
    await act(() => vi.advanceTimersByTimeAsync(IDLE_POLL_MS * 2))
    expect(getLocalFolder).toHaveBeenCalledTimes(5)
  })
})

describe('folder selection reconnects this machine', () => {
  it('refreshes after linking from an unlinked render and waits for the actual session', async () => {
    vi.useFakeTimers()
    const deps = fakeDeps({
      getLocalFolder: vi.fn(async () =>
        view({
          bridge: { connected: false, tools_installed: {} }
        })
      )
    })
    const { result, rerender } = renderHook(({ linked }) => useLocalFolder('p1', linked, deps), {
      initialProps: { linked: false }
    })
    await act(() => vi.advanceTimersByTimeAsync(0))
    const link = result.current.link
    rerender({ linked: true })
    await act(() => link('/home/u/rover-fw'))
    expect(result.current.status).toBe('loading')
    expect(linkedFolderPresentation(result.current.view, result.current.status).bridgeOffline).toBe(
      false
    )
    const calls = vi.mocked(deps.getLocalFolder).mock.calls.length
    expect(calls).toBeGreaterThanOrEqual(1)
    expect(deps.getLocalFolder).toHaveBeenLastCalledWith('p1', MACHINE.id)
    vi.mocked(deps.getLocalFolder).mockResolvedValue(view())
    await act(() => vi.advanceTimersByTimeAsync(SYNCING_POLL_MS))
    expect(result.current.view?.bridge.connected).toBe(true)
    expect(result.current.status).toBe('ready')
  })

  it('eventually reports a companion that stays disconnected without hiding it forever', async () => {
    vi.useFakeTimers()
    const deps = fakeDeps({
      getLocalFolder: vi.fn(async () =>
        view({
          source: source({ status: 'connected' }),
          bridge: { connected: false, tools_installed: {} }
        })
      )
    })
    const { result } = renderHook(() => useLocalFolder('p1', true, deps))
    await act(() => vi.advanceTimersByTimeAsync(0))
    await act(() => result.current.link('/home/u/rover-fw'))
    expect(result.current.status).toBe('loading')
    await act(() => vi.advanceTimersByTimeAsync(30_000))
    expect(result.current.status).toBe('ready')
    expect(linkedFolderPresentation(result.current.view, result.current.status).bridgeOffline).toBe(
      true
    )
  })
})

it('does not expose the previous folder or poll it while a replacement link is pending', async () => {
  vi.useFakeTimers()
  let finish!: (value: { source: Source; job_id: string }) => void
  const deps = fakeDeps({
    linkLocalFolder: vi.fn(
      () =>
        new Promise<{ source: Source; job_id: string }>((resolve) => {
          finish = resolve
        })
    )
  })
  const { result } = renderHook(() => useLocalFolder('p1', true, deps))
  await act(() => vi.advanceTimersByTimeAsync(0))
  let pending!: Promise<void>
  act(() => {
    pending = result.current.link('/home/u/new-folder')
  })
  expect(result.current.view).toBeNull()
  expect(await result.current.open('old-entity', 'vscode')).toBeNull()
  const calls = vi.mocked(deps.getLocalFolder).mock.calls.length
  await act(() => vi.advanceTimersByTimeAsync(SYNCING_POLL_MS))
  expect(deps.getLocalFolder).toHaveBeenCalledTimes(calls)
  await act(async () => {
    finish({ source: source(), job_id: 'j1' })
    await pending
  })
  expect(deps.getLocalFolder).toHaveBeenCalledTimes(calls + 1)
})

it('loads a new project while the previous project link is unresolved and ignores its completion', async () => {
  let finish!: (value: { source: Source; job_id: string }) => void
  const deps = fakeDeps({
    linkLocalFolder: vi.fn(
      () =>
        new Promise<{ source: Source; job_id: string }>((resolve) => {
          finish = resolve
        })
    ),
    getLocalFolder: vi.fn(async (project) =>
      view({ source: source({ id: project, project_id: project }) })
    )
  })
  const { result, rerender } = renderHook(({ project }) => useLocalFolder(project, true, deps), {
    initialProps: { project: 'p1' }
  })
  await waitFor(() => expect(result.current.view?.source?.id).toBe('p1'))
  let pending!: Promise<void>
  act(() => {
    pending = result.current.link('/home/u/old-folder')
  })
  rerender({ project: 'p2' })
  await waitFor(() => expect(result.current.view?.source?.id).toBe('p2'))
  await act(async () => {
    finish({ source: source(), job_id: 'j1' })
    await pending
  })
  expect(result.current.view?.source?.id).toBe('p2')
  expect(deps.getLocalFolder).toHaveBeenLastCalledWith('p2', MACHINE.id)
})

it.each(['switch', 'unmount'] as const)(
  'never links the departed scope when machine identity resolves after %s',
  async (action) => {
    let identify!: (value: typeof MACHINE) => void
    const deps = fakeDeps({
      machine: vi.fn(
        () =>
          new Promise<typeof MACHINE>((resolve) => {
            identify = resolve
          })
      )
    })
    const { result, rerender, unmount } = renderHook(
      ({ project }) => useLocalFolder(project, true, deps),
      {
        initialProps: { project: 'p1' }
      }
    )
    let pending!: Promise<void>
    act(() => {
      pending = result.current.link('/home/u/old-folder')
    })
    if (action === 'switch') rerender({ project: 'p2' })
    else unmount()
    await act(async () => {
      identify(MACHINE)
      await pending
    })
    expect(deps.linkLocalFolder).not.toHaveBeenCalled()
    if (action === 'switch') {
      await waitFor(() => expect(deps.getLocalFolder).toHaveBeenCalledWith('p2', MACHINE.id))
      expect(result.current.status).toBe('ready')
    }
  }
)

it.each(['post', 'get'] as const)(
  'ends reconnecting at its deadline even when the %s never settles',
  async (request) => {
    vi.useFakeTimers()
    const never = new Promise<never>(() => undefined)
    const deps = fakeDeps(
      request === 'post'
        ? { linkLocalFolder: vi.fn(() => never) }
        : { getLocalFolder: vi.fn(() => never) }
    )
    const { result } = renderHook(() => useLocalFolder('p1', true, deps))
    await act(() => vi.advanceTimersByTimeAsync(0))
    act(() => {
      void result.current.link('/home/u/folder')
    })
    await act(() => vi.advanceTimersByTimeAsync(30_001))
    expect(result.current.status).not.toBe('loading')
    if (request === 'get') expect(result.current.status).toBe('offline')
    expect(deps.linkLocalFolder).toHaveBeenCalledTimes(1)
  }
)
