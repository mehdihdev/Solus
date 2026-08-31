// Machine-local project→folder links (SOLUSDEV-164). A folder path is specific
// to this computer, so it is persisted locally (never sent to the API).
// SOLUSDEV-166: localStorage is now the DISPLAY CACHE — the durable copy is
// ~/.solus/projects.json, owned by the main process and reached over IPC.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { hydrateProjectFolders, useProjectFolderStore } from './projectFolderStore'

interface FolderBridgeStub {
  link: ReturnType<typeof vi.fn>
  unlink: ReturnType<typeof vi.fn>
  links: ReturnType<typeof vi.fn>
}

function installBridge(): FolderBridgeStub {
  const bridge: FolderBridgeStub = {
    link: vi.fn().mockResolvedValue({ ok: true }),
    unlink: vi.fn().mockResolvedValue({ ok: true }),
    links: vi.fn().mockResolvedValue({})
  }
  ;(window as unknown as { solus?: unknown }).solus = { folder: bridge }
  return bridge
}

beforeEach(() => {
  useProjectFolderStore.setState({ folders: {} })
  delete (window as unknown as { solus?: unknown }).solus
})

describe('projectFolderStore', () => {
  it('links and reads a folder for a project', () => {
    useProjectFolderStore.getState().setFolder('p1', { path: '/home/u/arm', repoUrl: 'r' })
    expect(useProjectFolderStore.getState().folders['p1']).toEqual({
      path: '/home/u/arm',
      repoUrl: 'r'
    })
  })

  it('keeps links per project without cross-contamination', () => {
    const store = useProjectFolderStore.getState()
    store.setFolder('p1', { path: '/a' })
    store.setFolder('p2', { path: '/b' })
    const { folders } = useProjectFolderStore.getState()
    expect(folders['p1'].path).toBe('/a')
    expect(folders['p2'].path).toBe('/b')
  })

  it('clears a project link immutably', () => {
    const store = useProjectFolderStore.getState()
    store.setFolder('p1', { path: '/a' })
    const before = useProjectFolderStore.getState().folders
    store.clearFolder('p1')
    expect(useProjectFolderStore.getState().folders['p1']).toBeUndefined()
    // Original object not mutated (immutability rule).
    expect(before['p1']).toEqual({ path: '/a' })
  })
})

describe('write-through to the ~/.solus registry (SOLUSDEV-166)', () => {
  it('setFolder writes through to the machine registry', () => {
    const bridge = installBridge()
    useProjectFolderStore.getState().setFolder('p1', { path: '/a', repoUrl: 'r' })
    expect(bridge.link).toHaveBeenCalledWith('p1', { path: '/a', repoUrl: 'r' })
    // The cache updates optimistically regardless.
    expect(useProjectFolderStore.getState().folders['p1']).toEqual({ path: '/a', repoUrl: 'r' })
  })

  it('clearFolder writes through to the machine registry', () => {
    const bridge = installBridge()
    useProjectFolderStore.getState().setFolder('p1', { path: '/a' })
    useProjectFolderStore.getState().clearFolder('p1')
    expect(bridge.unlink).toHaveBeenCalledWith('p1')
  })

  it('degrades to cache-only outside the desktop app (no bridge)', () => {
    useProjectFolderStore.getState().setFolder('p1', { path: '/a' })
    expect(useProjectFolderStore.getState().folders['p1']).toEqual({ path: '/a' })
  })

  it('a rejected IPC write never breaks the UI update', () => {
    const bridge = installBridge()
    bridge.link.mockRejectedValue(new Error('registry read-only'))
    useProjectFolderStore.getState().setFolder('p1', { path: '/a' })
    expect(useProjectFolderStore.getState().folders['p1']).toEqual({ path: '/a' })
  })
})

describe('hydrateProjectFolders', () => {
  it('merges the registry into the cache, registry winning on conflicts', async () => {
    const bridge = installBridge()
    bridge.links.mockResolvedValue({
      p1: { path: '/registry/rover', repoUrl: 'r', lastOpenedAt: '2026-08-30T12:00:00Z' },
      p2: { path: '/registry/arm' }
    })
    useProjectFolderStore.setState({
      folders: { p1: { path: '/stale/cache' }, p3: { path: '/cache/only' } }
    })
    await hydrateProjectFolders()
    const { folders } = useProjectFolderStore.getState()
    expect(folders['p1']).toEqual({ path: '/registry/rover', repoUrl: 'r' })
    expect(folders['p2']).toEqual({ path: '/registry/arm' })
    expect(folders['p3']).toEqual({ path: '/cache/only' })
  })

  it('is a no-op without the bridge, and survives a failing bridge', async () => {
    await hydrateProjectFolders() // no bridge installed
    const bridge = installBridge()
    bridge.links.mockRejectedValue(new Error('down'))
    await hydrateProjectFolders()
    expect(useProjectFolderStore.getState().folders).toEqual({})
  })
})
