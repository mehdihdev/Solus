// SOLUSDEV-321 P0-T3: what the SOL PAGE adds to a send beyond the typed text — where the
// person is looking (the workspace focus) and the chat's pinned nodes, each in a field of its
// own so the server can say WHY each one is in the context. The SOL window is a separate
// renderer with no workspace focus and no pins; it does not call this.
import { MAX_FOCUS_PATH } from '@solus/shared-types'
import { useFocusStore } from '../workspace/focusStore'
import { MAX_MENTIONS } from './mentionToken'
import type { StreamSolMessageInput } from './solApi'

export type PageAnchors = Pick<StreamSolMessageInput, 'focus' | 'pins'>

// The server parses every anchor id as a UUID and refuses the WHOLE turn (422) on one that is
// not. Nothing on the client guarantees it: the focus store sets the id before its neighbourhood
// loads and keeps it when the load fails, an extension's `focus.propose` takes any string, and an
// `[entity:…]` citation names whatever the model wrote. So a non-UUID is dropped here, never sent.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const uuids = (ids: readonly string[]): string[] => ids.filter((id) => UUID.test(id))

/**
 * The focus and pins of one page send, read at submit time — a focus is where the person is
 * NOW, not where they were when the page mounted. Non-UUID ids are dropped, then both lists are
 * trimmed to what the server accepts (a deep trail keeps its nearest steps, the pins keep their
 * first eight): these fields ride every send, and a 422 would cost the person their question.
 */
export function pageAnchors(pinnedIds: readonly string[]): PageAnchors {
  const { focusedEntityId, path } = useFocusStore.getState()
  const pins = uuids(pinnedIds).slice(0, MAX_MENTIONS)
  return {
    ...(focusedEntityId && UUID.test(focusedEntityId)
      ? {
          focus: {
            entityId: focusedEntityId,
            path: uuids(path.map((step) => step.entity.entityId)).slice(-MAX_FOCUS_PATH)
          }
        }
      : {}),
    ...(pins.length > 0 ? { pins } : {})
  }
}
