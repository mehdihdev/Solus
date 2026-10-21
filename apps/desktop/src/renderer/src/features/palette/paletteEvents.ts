// SOLUSDEV-317 — `search.palette_opened`: a ⌘K result was opened (API.md §2.13).
// What kind, at which rank, after how long a query — never the query text or
// the result's label, which can carry ingested content. Best effort, like
// every client event: consent is gated server-side and a failed post is dropped.
import { postDataEvents } from '../../lib/api/resources.extensions'
import { devBypassActive } from '../../lib/supabase'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { PaletteKind } from './paletteItems'

/** Mirrors the server schema's bound. */
export const MAX_QUERY_LENGTH = 200

export function reportPaletteOpened(kind: PaletteKind, rank: number, query: string): void {
  if (devBypassActive || useAuthStore.getState().status !== 'authenticated') return
  const projectId = useWorkspaceStore.getState().project?.id
  void postDataEvents([
    {
      event_type: 'search.palette_opened',
      ...(projectId ? { project_id: projectId } : {}),
      payload: { kind, rank, query_length: Math.min(query.length, MAX_QUERY_LENGTH) }
    }
  ]).catch(() => undefined)
}
