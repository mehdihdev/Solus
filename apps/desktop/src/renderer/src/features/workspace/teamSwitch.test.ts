// SOLUSDEV-244 / HOME H5: a team switch is a BROADER swap than a project
// switch — the open project (if it belongs to another team) and everything
// scoped to it go, and the project list reloads for the new team.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { switchWorkspaceTeam } from './teamSwitch'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import { useFocusStore } from './focusStore'
import { useShellStore } from './shellStore'
import { useExtensionsStore } from '../extensions/extensionsStore'
import { selectSession, useSolChatStore, EMPTY_SESSION } from '../sol/solChatStore'
import * as ext from '../../lib/api/resources.extensions'
import type { Neighborhood } from '../../lib/api/resources'

const bypass = vi.hoisted(() => ({ active: false }))
vi.mock('../../lib/supabase', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/supabase')>()),
  get devBypassActive() {
    return bypass.active
  }
}))
vi.mock('../../lib/api/resources.extensions', async (importOriginal) => ({
  ...(await importOriginal<typeof ext>()),
  postDataEvents: vi.fn(async () => undefined)
}))

const A = { id: 'p-a', name: 'Rover', teamId: 't1' }
const NEIGHBORHOOD: Neighborhood = { entities: [], relations: [] } as unknown as Neighborhood

function seedProjectAOfTeam1(): void {
  useWorkspaceStore.setState({ project: A, teamId: 't1', linked: true })
  useFocusStore.setState({
    focusedEntityId: 'e1',
    status: 'ready',
    cache: { 'p-a:e1@1': NEIGHBORHOOD }
  })
  useExtensionsStore.getState().select('bom')
  useShellStore
    .getState()
    .setToast({ title: 'SOL replied', body: '…', action: 'View', screen: 'sol' })
  useSolChatStore.setState({
    sessions: { 'p-a': { ...EMPTY_SESSION, conversationId: 'conv-a', items: [] } }
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  bypass.active = false
  useWorkspaceStore.getState().reset()
  useFocusStore.getState().reset()
  useShellStore.getState().reset()
  useExtensionsStore.getState().reset()
  useSolChatStore.setState({ sessions: {} })
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@example.dev' } as never })
})

describe('switchWorkspaceTeam', () => {
  it('closes a project of the previous team and clears everything scoped to it', () => {
    seedProjectAOfTeam1()
    switchWorkspaceTeam('t2', 'home')
    const ws = useWorkspaceStore.getState()
    expect(ws.teamId).toBe('t2')
    expect(ws.project).toBeNull()
    expect(useFocusStore.getState().cache).toEqual({})
    expect(useFocusStore.getState().focusedEntityId).toBeNull()
    expect(useExtensionsStore.getState().selectedId).toBeNull()
    expect(useShellStore.getState().toast).toBeNull()
    // A's transcript stays parked under A (SOLUSDEV-233) and is never selected
    // for "no project".
    expect(selectSession(useSolChatStore.getState(), null)).toBe(EMPTY_SESSION)
  })

  it('keeps the open project when it already belongs to the target team', () => {
    seedProjectAOfTeam1()
    switchWorkspaceTeam('t1', 'home')
    expect(useWorkspaceStore.getState().project).toEqual(A)
    expect(useExtensionsStore.getState().selectedId).toBe('bom')
  })

  it('is a no-op when the team is already active and no project is open', () => {
    useWorkspaceStore.setState({ project: null, teamId: 't2', linked: true })
    switchWorkspaceTeam('t2', 'home')
    expect(useWorkspaceStore.getState().teamId).toBe('t2')
    expect(vi.mocked(ext.postDataEvents)).not.toHaveBeenCalled()
  })

  it('reports the switch as a data event, with the surface and the closed project', () => {
    seedProjectAOfTeam1()
    switchWorkspaceTeam('t2', 'home')
    const calls = vi.mocked(ext.postDataEvents).mock.calls.flat().flat()
    const teamEvent = calls.find(
      (e) => (e as { event_type: string }).event_type === 'team.switched'
    )
    expect(teamEvent).toMatchObject({
      event_type: 'team.switched',
      payload: { from_team_id: 't1', to_team_id: 't2', closed_project_id: 'p-a', surface: 'home' }
    })
  })

  it('never reports under the dev bypass', () => {
    bypass.active = true
    seedProjectAOfTeam1()
    switchWorkspaceTeam('t2', 'home')
    expect(vi.mocked(ext.postDataEvents)).not.toHaveBeenCalled()
    expect(useWorkspaceStore.getState().teamId).toBe('t2')
  })
})
