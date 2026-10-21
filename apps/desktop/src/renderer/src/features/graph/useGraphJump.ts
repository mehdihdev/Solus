// SOLUSDEV-317 — serves a ⌘K node pick on the Workspace screen. The palette
// leaves a jump request in its store and navigates here; once this project's
// graph is loaded, the request is handed to the screen's own reveal (which
// enters the node's level, centres it and selects it) and consumed. A node
// that is no longer in the graph, or a jump left waiting too long, is dropped instead.
import { useEffect } from 'react'
import type { Entity } from '../../lib/api/resources'
import { JUMP_TTL_MS, usePaletteStore } from '../palette/paletteStore'

export function useGraphJump(
  projectId: string | null,
  entities: readonly Entity[] | null,
  onReveal: (entityId: string) => void
): void {
  const jump = usePaletteStore((s) => s.jump)
  useEffect(() => {
    if (!jump || !projectId || jump.projectId !== projectId || !entities) return
    // An expired jump is dropped: a graph that loads on a later, unrelated visit must not
    // select a node picked long ago. (A TTL, not an unmount cleanup — StrictMode remounts.)
    const fresh = Date.now() - jump.requestedAt <= JUMP_TTL_MS
    if (fresh && entities.some((entity) => entity.id === jump.entityId)) onReveal(jump.entityId)
    usePaletteStore.getState().consumeJump(jump.sequence)
  }, [jump, projectId, entities, onReveal])
}
