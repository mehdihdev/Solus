import { describe, it, expect, beforeEach } from 'vitest'
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
