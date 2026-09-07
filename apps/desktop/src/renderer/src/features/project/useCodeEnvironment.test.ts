// SOLUSDEV-250 (I3) — the Code environment row's data hook: loads this
// machine's view only when the project has a local source linked HERE, polls
// slowly and on window focus, keeps the last view when a poll fails, and goes
// offline honestly when the first read fails.
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Source } from '../../lib/api/resources'
import {
  EMPTY_CODE_ENVIRONMENT_VIEW,
  type CodeEnvironmentView
} from '../../lib/api/resources.codeenv'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { CODE_ENVIRONMENT_POLL_MS } from './codeEnvironment.constants'
import { useCodeEnvironment, type CodeEnvironmentDeps } from './useCodeEnvironment'

const MACHINE = { id: '0123456789abcdef0123456789abcdef', name: 'mehdi-mbp' }

const source = (over: Partial<Source> = {}): Source => ({
  id: 's1',
  project_id: 'p1',
  type: 'local',
  name: 'mehdi-mbp',
  status: 'connected',
  config: { machine_id: MACHINE.id, machine_name: MACHINE.name, folder_name: 'rover-fw' },
  account_login: null,
  last_synced_at: null,
  last_error: null,
  created_at: '',
  updated_at: '',
  ...over
})

const view = (over: Partial<CodeEnvironmentView> = {}): CodeEnvironmentView => ({
  ...EMPTY_CODE_ENVIRONMENT_VIEW,
  source: source(),
  bridge: { connected: true, code_server: true },
  ...over
})

function fakeDeps(over: Partial<CodeEnvironmentDeps> = {}): CodeEnvironmentDeps {
  return {
    machine: vi.fn(async () => MACHINE),
    getCodeEnvironment: vi.fn(async () => view()),
    ...over
  }
}

beforeEach(() => {
  useWorkspaceStore.setState({ linked: true })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useCodeEnvironment — gating', () => {
  it('loads the view for the current project and this machine', async () => {
    const deps = fakeDeps()
    const { result } = renderHook(() => useCodeEnvironment('p1', [source()], deps))

    await waitFor(() => expect(result.current.status).toBe('ready'))

    expect(deps.getCodeEnvironment).toHaveBeenCalledWith('p1', MACHINE.id)
    expect(result.current.view?.bridge.code_server).toBe(true)
    expect(result.current.source?.id).toBe('s1')
  })

  it('fetches nothing when the project has no local source on THIS machine', async () => {
    const deps = fakeDeps()
    const elsewhere = source({ id: 's2', config: { machine_id: 'other-machine' } })
    const { result } = renderHook(() => useCodeEnvironment('p1', [elsewhere], deps))

    await waitFor(() => expect(deps.machine).toHaveBeenCalled())
    await act(async () => {})

    expect(deps.getCodeEnvironment).not.toHaveBeenCalled()
    expect(result.current.source).toBeNull()
    expect(result.current.status).toBe('idle')
  })

  it('fetches nothing without a project or when the bridge has no companion id', async () => {
    const noMachine = fakeDeps({ machine: vi.fn(async () => null) })
    const { result } = renderHook(() => useCodeEnvironment('p1', [source()], noMachine))
    await waitFor(() => expect(noMachine.machine).toHaveBeenCalled())
    await act(async () => {})
    expect(noMachine.getCodeEnvironment).not.toHaveBeenCalled()
    expect(result.current.source).toBeNull()

    const deps = fakeDeps()
    renderHook(() => useCodeEnvironment(null, [source()], deps))
    await act(async () => {})
    expect(deps.getCodeEnvironment).not.toHaveBeenCalled()
  })

  it('fetches nothing while the workspace cannot reach the API', async () => {
    useWorkspaceStore.setState({ linked: false })
    const deps = fakeDeps()
    renderHook(() => useCodeEnvironment('p1', [source()], deps))
    await act(async () => {})
    expect(deps.getCodeEnvironment).not.toHaveBeenCalled()
  })
})

describe('useCodeEnvironment — failure', () => {
  it('goes offline honestly when the first read fails', async () => {
    const deps = fakeDeps({
      getCodeEnvironment: vi.fn(async () => Promise.reject(new Error('down')))
    })
    const { result } = renderHook(() => useCodeEnvironment('p1', [source()], deps))
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(result.current.view).toBeNull()
  })

  it('keeps the last view when a later poll fails', async () => {
    const get = vi.fn(async () => view())
    const deps = fakeDeps({ getCodeEnvironment: get })
    const { result } = renderHook(() => useCodeEnvironment('p1', [source()], deps))
    await waitFor(() => expect(result.current.status).toBe('ready'))

    get.mockRejectedValueOnce(new Error('blip'))
    await act(() => result.current.refresh())

    expect(result.current.status).toBe('ready')
    expect(result.current.view?.bridge.code_server).toBe(true)
  })
})

describe('useCodeEnvironment — cadence', () => {
  it('re-reads every 30 s', async () => {
    vi.useFakeTimers()
    const deps = fakeDeps()
    const { result } = renderHook(() => useCodeEnvironment('p1', [source()], deps))
    await act(() => vi.advanceTimersByTimeAsync(0))
    expect(result.current.status).toBe('ready')
    expect(deps.getCodeEnvironment).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(CODE_ENVIRONMENT_POLL_MS)
    })
    expect(deps.getCodeEnvironment).toHaveBeenCalledTimes(2)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CODE_ENVIRONMENT_POLL_MS)
    })
    expect(deps.getCodeEnvironment).toHaveBeenCalledTimes(3)
  })

  it('re-reads when the window regains focus, and stops after unmount', async () => {
    const deps = fakeDeps()
    const { result, unmount } = renderHook(() => useCodeEnvironment('p1', [source()], deps))
    await waitFor(() => expect(result.current.status).toBe('ready'))

    await act(async () => {
      window.dispatchEvent(new Event('focus'))
    })
    expect(deps.getCodeEnvironment).toHaveBeenCalledTimes(2)

    unmount()
    await act(async () => {
      window.dispatchEvent(new Event('focus'))
    })
    expect(deps.getCodeEnvironment).toHaveBeenCalledTimes(2)
  })

  it('never paints a response for a project the hook has since left', async () => {
    let release: (value: CodeEnvironmentView) => void = () => undefined
    const slow = new Promise<CodeEnvironmentView>((resolve) => {
      release = resolve
    })
    const get = vi
      .fn<CodeEnvironmentDeps['getCodeEnvironment']>()
      .mockImplementationOnce(() => slow)
      .mockImplementation(async () => view({ requirements: { count: 7, files: [] } }))
    const deps = fakeDeps({ getCodeEnvironment: get })
    const { result, rerender } = renderHook(
      ({ projectId }) => useCodeEnvironment(projectId, [source()], deps),
      { initialProps: { projectId: 'p1' } }
    )
    await waitFor(() => expect(get).toHaveBeenCalledWith('p1', MACHINE.id))

    rerender({ projectId: 'p2' })
    await waitFor(() => expect(result.current.view?.requirements.count).toBe(7))
    await act(async () => {
      release(view({ requirements: { count: 1, files: [] } }))
    })

    expect(result.current.view?.requirements.count).toBe(7)
  })
})
