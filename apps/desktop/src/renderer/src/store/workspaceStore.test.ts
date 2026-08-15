import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { useWorkspaceStore } from './workspaceStore'

describe('workspaceStore', () => {
  beforeEach(() => {
    useWorkspaceStore.getState().reset()
  })

  it('starts empty and unlinked', () => {
    const s = useWorkspaceStore.getState()
    expect(s.teamId).toBeNull()
    expect(s.project).toBeNull()
    expect(s.linked).toBe(false)
  })

  it('stores team, project, and link status', () => {
    useWorkspaceStore.getState().setTeamId('team-1')
    useWorkspaceStore.getState().setProject({ id: 'p1', name: 'Strider' })
    useWorkspaceStore.getState().setLinked(true)
    const s = useWorkspaceStore.getState()
    expect(s.teamId).toBe('team-1')
    expect(s.project).toEqual({ id: 'p1', name: 'Strider' })
    expect(s.linked).toBe(true)
  })

  it('reset clears everything', () => {
    useWorkspaceStore.getState().setProject({ id: 'p1', name: 'X' })
    useWorkspaceStore.getState().reset()
    expect(useWorkspaceStore.getState().project).toBeNull()
  })
})

// The companion's bridge URL is project-scoped, and it is fixed in the child's
// environment at spawn. Nothing told the main process which project was open,
// so the companion dialled a project-less URL that matched no route and the API
// answered 403 on every retry — the bridge could never connect.
describe('workspaceStore — relays the project to the companion', () => {
  const setProject = vi.fn(() => Promise.resolve())

  beforeEach(() => {
    setProject.mockClear()
    ;(window as unknown as { solus?: unknown }).solus = { bridge: { setProject } }
    useWorkspaceStore.getState().reset()
    setProject.mockClear() // reset() itself relays; ignore that for these cases
  })

  afterEach(() => {
    delete (window as unknown as { solus?: unknown }).solus
  })

  it('relays the id when a project is opened', () => {
    useWorkspaceStore.getState().setProject({ id: 'p1', name: 'Rover' })
    expect(setProject).toHaveBeenCalledWith('p1')
  })

  it('relays null when the project is cleared, so the companion stops dialling', () => {
    useWorkspaceStore.getState().setProject(null)
    expect(setProject).toHaveBeenCalledWith(null)
  })

  it('relays on reset too — a signed-out app must not keep a bridge open', () => {
    useWorkspaceStore.getState().setProject({ id: 'p1', name: 'Rover' })
    setProject.mockClear()
    useWorkspaceStore.getState().reset()
    expect(setProject).toHaveBeenCalledWith(null)
  })

  it('does not throw outside Electron, where there is no bridge', () => {
    delete (window as unknown as { solus?: unknown }).solus
    expect(() => useWorkspaceStore.getState().setProject({ id: 'p1', name: 'Rover' })).not.toThrow()
  })
})

// Relaying from `setProject` alone was not enough, and this is the case that
// matters most: zustand's `persist` REHYDRATES BY SETTING STATE DIRECTLY — it
// never calls the store's actions. So opening the app with a project already in
// localStorage — the normal case — relayed nothing, main never learned the
// project, the companion was never spawned, and the pill read "Bridge offline".
// Rehydration happens at store construction, so these cases need a fresh module.
describe('workspaceStore — relays a REHYDRATED project on startup', () => {
  afterEach(() => {
    delete (window as unknown as { solus?: unknown }).solus
    localStorage.clear()
    vi.resetModules()
  })

  async function bootWith(stored: unknown): Promise<ReturnType<typeof vi.fn>> {
    const setProject = vi.fn(() => Promise.resolve())
    localStorage.clear()
    if (stored !== undefined) {
      localStorage.setItem('solus_workspace_v1', JSON.stringify({ state: stored, version: 0 }))
    }
    ;(window as unknown as { solus?: unknown }).solus = { bridge: { setProject } }
    vi.resetModules()
    await import('./workspaceStore')
    return setProject
  }

  it('tells the companion about a project restored from localStorage', async () => {
    const setProject = await bootWith({
      teamId: 't1',
      project: { id: 'p1', name: 'Rover' },
      linked: true
    })

    // Nobody touched the store — this must fire from rehydration alone.
    expect(setProject).toHaveBeenCalledWith('p1')
  })

  it('relays null when nothing was stored, so no companion is spawned', async () => {
    const setProject = await bootWith(undefined)
    expect(setProject).not.toHaveBeenCalledWith(expect.stringMatching(/./))
  })

  it('survives a stored workspace with no project', async () => {
    const setProject = await bootWith({ teamId: 't1', project: null, linked: true })
    expect(setProject).toHaveBeenCalledWith(null)
  })
})
