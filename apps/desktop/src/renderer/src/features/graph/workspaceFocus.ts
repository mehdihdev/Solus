import { useWorkspaceStore } from '../../store/workspaceStore'
import { useFocusStore } from '../workspace/focusStore'
import { toSharedFocus } from '../workspace/useSharedFocus'
import type { Entity, Relation } from '../../lib/api/resources'
import { buildNavigationIndex } from './navigation/graphIndex'

/** A graph mutation invalidates every cached neighborhood containing its changed links. */
export async function refreshWorkspaceFocus(projectId: string, removedId?: string): Promise<void> {
  if (useWorkspaceStore.getState().project?.id !== projectId) return
  const { focusedEntityId, path, clearProject, focus } = useFocusStore.getState()
  clearProject()
  if (focusedEntityId && focusedEntityId !== removedId) await focus(focusedEntityId, path)
}

/** Reconcile against committed graph data, never refetch a removed container. */
export async function reconcileWorkspaceFocus(
  projectId: string,
  entities: readonly Entity[],
  relations: readonly Relation[]
): Promise<void> {
  if (useWorkspaceStore.getState().project?.id !== projectId) return
  const { focusedEntityId, clearProject, focus } = useFocusStore.getState()
  clearProject()
  if (!focusedEntityId || !entities.some((entity) => entity.id === focusedEntityId)) return
  const path = buildNavigationIndex(entities, relations)
    .pathTo(focusedEntityId)
    .flatMap((step) => {
      const shared = toSharedFocus(step.entity, projectId)
      return shared
        ? [
            {
              entity: shared.entity,
              domain: shared.domain,
              label: shared.label,
              relation: step.relation
            }
          ]
        : []
    })
  await focus(focusedEntityId, path)
}
