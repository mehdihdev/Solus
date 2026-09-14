// SOLUSDEV-242: the switch choke point leaves no project-scoped state behind.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { switchWorkspaceProject } from './projectSwitch'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import { useFocusStore } from './focusStore'
import { useShellStore } from './shellStore'
import { useExtensionsStore } from '../extensions/extensionsStore'
import { selectSession, useSolChatStore, EMPTY_SESSION } from '../sol/solChatStore'
import { selectConversationId, useSolSessionStore } from '../sol/solSessionStore'
import { useSolWindowStore } from '../sol/solWindowStore'
import { SOL_REGION } from '../sol/solWindow.fixtures'
import * as ext from '../../lib/api/resources.extensions'
import type { Neighborhood } from '../../lib/api/resources'

// The dev bypass reads `authenticated` but has no token the API accepts; the
// switch event must not fire under it. Off by default here so the reporting
// tests exercise the real path.
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
const B = { id: 'p-b', name: 'Arm', teamId: 't2' }
const NEIGHBORHOOD: Neighborhood = { entities: [], relations: [] } as unknown as Neighborhood

const CONFIRMATION = {
  confirmationId: 'c1',
  tool: 'graph.delete_entity',
  args: { id: 'e1' },
  summary: 'Delete entity e1'
} as never

function seedProjectA(): void {
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
    sessions: {
      'p-a': {
        ...EMPTY_SESSION,
        conversationId: 'conv-a',
        items: [
          {
            id: 'm1',
            role: 'assistant',
            content: 'Shall I delete it?',
            citations: [],
            trace: [],
            pending: false,
            error: null,
            confirmations: [CONFIRMATION]
          }
        ]
      }
    }
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
  useSolSessionStore.setState({ conversationByProject: {} })
  useSolWindowStore.setState({ region: null })
  useAuthStore.setState({ status: 'unauthenticated', user: null })
})

describe('switchWorkspaceProject', () => {
  projectSwitchIsolationTests()
  projectSwitchStateAndEventsTests()
})

function projectSwitchIsolationTests(): void {
  it('swaps the project and its team, and clears everything scoped to the previous one', () => {
    seedProjectA()
    switchWorkspaceProject(B, 'home')
    const workspace = useWorkspaceStore.getState()
    expect(workspace.project).toEqual(B)
    expect(workspace.teamId).toBe('t2')
    // Focus: no entity, no cache — a cached neighbourhood is another project's data.
    expect(useFocusStore.getState().focusedEntityId).toBe(null)
    expect(useFocusStore.getState().cache).toEqual({})
    // Store detail page and the away-toast belong to project A.
    expect(useExtensionsStore.getState().selectedId).toBe(null)
    expect(useShellStore.getState().toast).toBe(null)
  })

  it('never selects project A’s parked confirmation for project B', () => {
    seedProjectA()
    expect(selectSession(useSolChatStore.getState(), 'p-a').items[0]?.confirmations).toHaveLength(1)
    switchWorkspaceProject(B, 'topbar')
    const current = useWorkspaceStore.getState().project?.id ?? null
    const session = selectSession(useSolChatStore.getState(), current)
    expect(session.items).toEqual([])
    expect(session.items.flatMap((m) => m.confirmations)).toEqual([])
    // A's session is intact for when the user returns — parked, not lost.
    expect(selectSession(useSolChatStore.getState(), 'p-a').items[0]?.confirmations).toHaveLength(1)
  })

  it('keeps the SOL window session keyed by project: B selects no conversation, A keeps its own (SOLUSDEV-252)', () => {
    seedProjectA()
    useSolSessionStore.getState().setConversation('p-a', 'conv-a')
    switchWorkspaceProject(B, 'home')
    const session = useSolSessionStore.getState()
    expect(selectConversationId(session, useWorkspaceStore.getState().project?.id ?? null)).toBe(
      null
    )
    expect(selectConversationId(session, 'p-a')).toBe('conv-a')
  })

  it('drops the circled screen region — pixels of the previous project (SOLUSDEV-252 FIX-2-R H1)', () => {
    seedProjectA()
    useSolWindowStore.getState().setRegion(SOL_REGION)
    switchWorkspaceProject(B, 'home')
    expect(useSolWindowStore.getState().region).toBeNull()
  })
}

function projectSwitchStateAndEventsTests(): void {
  it('switching to no project clears the same state', () => {
    seedProjectA()
    switchWorkspaceProject(null, 'validation')
    expect(useWorkspaceStore.getState().project).toBe(null)
    expect(useFocusStore.getState().cache).toEqual({})
    expect(useShellStore.getState().toast).toBe(null)
  })

  it('re-selecting the current project refreshes its name and team without clearing', () => {
    seedProjectA()
    switchWorkspaceProject({ ...A, name: 'Rover MK2' }, 'home')
    expect(useWorkspaceStore.getState().project?.name).toBe('Rover MK2')
    expect(useFocusStore.getState().focusedEntityId).toBe('e1')
    expect(useShellStore.getState().toast).not.toBe(null)
  })

  it('keeps the stored team when the project carries none (pre-242 state)', () => {
    useWorkspaceStore.setState({ teamId: 't1' })
    switchWorkspaceProject({ id: 'p-x', name: 'Legacy' }, 'home')
    expect(useWorkspaceStore.getState().teamId).toBe('t1')
  })

  it('reports the switch as a data event when signed in, naming the previous project and surface', () => {
    seedProjectA()
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' } })
    switchWorkspaceProject(B, 'topbar')
    expect(vi.mocked(ext.postDataEvents)).toHaveBeenCalledWith([
      {
        event_type: 'project.switched',
        project_id: 'p-b',
        payload: { from_project_id: 'p-a', surface: 'topbar' }
      }
    ])
  })

  it('sends no data event under the dev bypass, for a no-op re-select, or when leaving to no project', () => {
    seedProjectA()
    bypass.active = true
    useAuthStore.setState({ status: 'authenticated', user: { email: 'dev@solus.local' } })
    switchWorkspaceProject(B, 'home')
    bypass.active = false
    useAuthStore.setState({ status: 'unauthenticated', user: null })
    useWorkspaceStore.setState({ project: A })
    switchWorkspaceProject(B, 'home')
    switchWorkspaceProject(null, 'validation')
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' } })
    useWorkspaceStore.setState({ project: B })
    switchWorkspaceProject(B, 'home')
    expect(vi.mocked(ext.postDataEvents)).not.toHaveBeenCalled()
  })
}
