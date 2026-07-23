// Machine-local project→folder links (SOLUSDEV-164). A folder path is specific
// to this computer, so it is persisted locally (never sent to the API).
import { describe, it, expect, beforeEach } from 'vitest'
import { useProjectFolderStore } from './projectFolderStore'

beforeEach(() => useProjectFolderStore.setState({ folders: {} }))

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
