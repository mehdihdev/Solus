import { beforeEach, expect, it, vi } from 'vitest'
import { useFocusStore } from '../workspace/focusStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { getGraphNeighborhood, type Entity, type Relation } from '../../lib/api/resources'
import { refreshWorkspaceFocus, reconcileWorkspaceFocus } from './workspaceFocus'
vi.mock('../../lib/api/resources', () => ({ getGraphNeighborhood: vi.fn() }))
beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover' }, linked: true })
  useFocusStore.getState().reset()
  vi.mocked(getGraphNeighborhood).mockResolvedValue({ entities: [], edges: [], truncated: false })
})
it('invalidates neighborhoods and reloads the surviving focus after mutation', async () => {
  await useFocusStore.getState().focus('note')
  await refreshWorkspaceFocus('p1')
  expect(getGraphNeighborhood).toHaveBeenCalledTimes(2)
  expect(useFocusStore.getState().focusedEntityId).toBe('note')
})
it('clears a deleted selected node without fetching it again', async () => {
  await useFocusStore.getState().focus('note')
  await refreshWorkspaceFocus('p1', 'note')
  expect(getGraphNeighborhood).toHaveBeenCalledTimes(1)
  expect(useFocusStore.getState().focusedEntityId).toBeNull()
  expect(useFocusStore.getState().cache).toEqual({})
})
it('does not clear or fetch another project after a delayed mutation', async () => {
  await useFocusStore.getState().focus('note')
  await refreshWorkspaceFocus('old-project')
  expect(getGraphNeighborhood).toHaveBeenCalledTimes(1)
  expect(useFocusStore.getState().focusedEntityId).toBe('note')
})

it('clears a deleted category without requesting its removed neighborhood', async () => {
  await useFocusStore.getState().focus('sensors')
  await reconcileWorkspaceFocus('p1', [], [])
  expect(getGraphNeighborhood).toHaveBeenCalledTimes(1)
  expect(useFocusStore.getState().focusedEntityId).toBeNull()
  expect(useFocusStore.getState().path).toEqual([])
})

it('keeps a retained part selected and rebuilds its surviving CAD ancestry', async () => {
  const entities: Entity[] = [
    { id: 'cad', name: 'CAD document', domain: 'mechanical', type: 'cad_document', source_key: '' },
    { id: 'motor', name: 'Motor', domain: 'mechanical', type: 'part', source_key: '' }
  ]
  const relations: Relation[] = [
    { id: 'cad-motor', type: 'contains', from_entity_id: 'cad', to_entity_id: 'motor' }
  ]
  await useFocusStore.getState().focus('motor', [
    {
      entity: { projectId: 'p1', entityId: 'deleted-robot' },
      domain: 'project',
      label: 'Robot',
      relation: 'contains'
    }
  ])
  await reconcileWorkspaceFocus('p1', entities, relations)
  expect(getGraphNeighborhood).toHaveBeenCalledTimes(2)
  expect(useFocusStore.getState().focusedEntityId).toBe('motor')
  expect(useFocusStore.getState().path).toEqual([
    {
      entity: { projectId: 'p1', entityId: 'cad' },
      domain: 'mechanical',
      label: 'CAD document',
      relation: 'contains'
    }
  ])
})

it('cannot reconcile another project after an old snapshot arrives', async () => {
  await useFocusStore.getState().focus('motor')
  await reconcileWorkspaceFocus('other', [], [])
  expect(useFocusStore.getState().focusedEntityId).toBe('motor')
  expect(getGraphNeighborhood).toHaveBeenCalledTimes(1)
})
