// NODES IN CONTEXT (design template): the nodes a person pinned to a chat. Client-side
// state — the API has no per-chat context set — sent as `mentions` on every send of that
// chat, merged with the `@`-mentions typed into the message. Persisted per account in
// localStorage (names are project content, so the account's end clears it); a fresh
// chat's pins live under `new` until the first send creates the conversation.
// ponytail: localStorage; a server-side set if pins must follow the account across machines.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Entity } from '../../lib/api/resources'
import { onAccountEnd, selectConversationId, useSolSessionStore } from './solSessionStore'

export interface PinnedNode {
  id: string
  name: string
  domain: string
  type: string
}

export interface PinnedContextState {
  pinsByChat: Readonly<Record<string, readonly PinnedNode[]>>
  /** A one-shot composer prefill ("Ask SOL" from the Workspace); never persisted. */
  draft: string | null
  pin: (key: string, node: PinnedNode) => void
  unpin: (key: string, entityId: string) => void
  clear: (key: string) => void
  /** The first send created the conversation: its `new` bucket becomes the chat's. */
  adoptConversation: (projectId: string, conversationId: string) => void
  setDraft: (text: string | null) => void
  resetForSignOut: () => void
}

export const PINNED_CONTEXT_STORAGE_KEY = 'solus_sol_pinned_v1'
const EMPTY: readonly PinnedNode[] = Object.freeze([])

export const chatKey = (projectId: string, conversationId: string | null): string =>
  `${projectId}:${conversationId ?? 'new'}`

export const selectPins = (
  state: Pick<PinnedContextState, 'pinsByChat'>,
  projectId: string | null,
  conversationId: string | null
): readonly PinnedNode[] =>
  projectId ? (state.pinsByChat[chatKey(projectId, conversationId)] ?? EMPTY) : EMPTY

export const usePinnedContextStore = create<PinnedContextState>()(
  persist(
    (set) => ({
      pinsByChat: {},
      draft: null,
      pin: (key, node) =>
        set((s) => {
          const current = s.pinsByChat[key] ?? EMPTY
          if (current.some((pinned) => pinned.id === node.id)) return s
          return { pinsByChat: { ...s.pinsByChat, [key]: [...current, node] } }
        }),
      unpin: (key, entityId) =>
        set((s) => ({
          pinsByChat: {
            ...s.pinsByChat,
            [key]: (s.pinsByChat[key] ?? EMPTY).filter((pinned) => pinned.id !== entityId)
          }
        })),
      clear: (key) =>
        set((s) => ({
          pinsByChat: Object.fromEntries(
            Object.entries(s.pinsByChat).filter(([existing]) => existing !== key)
          )
        })),
      adoptConversation: (projectId, conversationId) =>
        set((s) => {
          const fresh = chatKey(projectId, null)
          const pending = s.pinsByChat[fresh]
          if (!pending || pending.length === 0) return s
          const target = chatKey(projectId, conversationId)
          const rest = Object.fromEntries(
            Object.entries(s.pinsByChat).filter(([existing]) => existing !== fresh)
          )
          const merged = [...(s.pinsByChat[target] ?? EMPTY)]
          for (const node of pending) if (!merged.some((p) => p.id === node.id)) merged.push(node)
          return { pinsByChat: { ...rest, [target]: merged } }
        }),
      setDraft: (draft) => set({ draft }),
      resetForSignOut: () => set({ pinsByChat: {}, draft: null })
    }),
    {
      name: PINNED_CONTEXT_STORAGE_KEY,
      partialize: (s) => ({ pinsByChat: s.pinsByChat })
    }
  )
)

onAccountEnd(() => usePinnedContextStore.getState().resetForSignOut())

/** "Ask SOL" from the Workspace: pin the node to the project's active chat and seed the
 *  composer. The caller then navigates to the SOL page, which mounts and takes the draft. */
export function askSolAbout(
  projectId: string,
  entity: Pick<Entity, 'id' | 'name' | 'domain' | 'type'>
): void {
  const conversationId = selectConversationId(useSolSessionStore.getState(), projectId)
  const store = usePinnedContextStore.getState()
  store.pin(chatKey(projectId, conversationId), {
    id: entity.id,
    name: entity.name,
    domain: entity.domain,
    type: entity.type
  })
  store.setDraft(`About ${entity.name}: `)
}

/** Read and clear the one-shot draft (the composer does this on mount). */
export function takeDraft(): string | null {
  const { draft, setDraft } = usePinnedContextStore.getState()
  if (draft !== null) setDraft(null)
  return draft
}
