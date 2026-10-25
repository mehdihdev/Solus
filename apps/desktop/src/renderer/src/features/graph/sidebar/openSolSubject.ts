import { getDesktopSolBridge } from '../../../lib/desktopBridge'
import { useFocusStore } from '../../workspace/focusStore'
import { workspaceSessionGeneration } from '../workspaceSession'

/** Focus the subject, then open the SOL window — only if that focus is still current
 *  (same session, same entity, ready). Selection alone never makes a model call. */
export function openSolSubject(entityId: string): void {
  const generation = workspaceSessionGeneration()
  void useFocusStore
    .getState()
    .focus(entityId)
    .then(() => {
      const focus = useFocusStore.getState()
      if (
        generation === workspaceSessionGeneration() &&
        focus.status === 'ready' &&
        focus.focusedEntityId === entityId
      ) {
        getDesktopSolBridge()?.open()
      }
    })
    .catch(() => undefined)
}
