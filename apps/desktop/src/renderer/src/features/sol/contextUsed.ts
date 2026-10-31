// SOLUSDEV-321 P1-T6: how the SOL chat store keeps a turn's context manifest — onto the session,
// and, for the entities it anchored on, onto the graph as a glow. It lives here rather than in
// solChatStore.ts, which sits under its 800-line cap. (The frames that land on the assistant ITEM
// — the tier that answered, the ceiling reached, the redacted args — are applied in
// solChatItems.ts, beside the rest of the item logic.)
import { useWorkspaceStore } from '../../store/workspaceStore'
import { HIGHLIGHT_TTL_MS, useFocusStore } from '../workspace/focusStore'
import type { SolSession } from './solChatStore'
import type { SolStreamEvent } from './solStream'

/** The store's own `patchSession`, handed in so this module never imports the store at runtime. */
type PatchSession = (projectId: string, fn: (session: SolSession) => SolSession) => void

/** The turn's context manifest onto the session of its project — and, when that project is the one
 *  open, where SOL looked onto the graph. A highlight nobody renders is harmless, which is the SOL
 *  window's case: it has no graph, and its renderer's focus store is its own. */
export function applyContextUsed(
  patchSession: PatchSession,
  projectId: string,
  event: Extract<SolStreamEvent, { type: 'context_used' }>
): void {
  patchSession(projectId, (session) => ({
    ...session,
    contextUsed: {
      sections: event.sections,
      truncated: event.truncated,
      dropped: event.dropped,
      layers: event.layers,
      anchors: event.anchors,
      anchorsDropped: event.anchorsDropped
    }
  }))
  // Only the open project's graph can glow. Sessions outlive navigation, so a turn still streaming
  // for another project must not light — or, with no anchors, put out — the open project's glow:
  // its ids match no card here, but the store has one timer and this call would replace it.
  if (useWorkspaceStore.getState().project?.id !== projectId) return
  // No anchors (or a frame that predates them) puts out the last turn's glow: it is stale.
  const anchorIds = (event.anchors ?? []).map((anchor) => anchor.id)
  useFocusStore.getState().highlight(anchorIds, HIGHLIGHT_TTL_MS)
}
