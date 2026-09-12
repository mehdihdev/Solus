// SOLUSDEV-252 S3: the SOL session — the active conversation per project and
// the streaming flag. The parts of the retired orbStore the chat still needs;
// nothing orb-shaped (docs/architecture/sol-window.md §2).
//
// Persistence: the conversation map only. The SOL window (#/sol-window) is a
// SEPARATE renderer sharing localStorage, so persisting it lets both surfaces
// rehydrate into the same conversation. `streaming` is per-window truth and
// never persists.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { useAuthStore } from '../../store/authStore'

export interface SolSessionState {
  /** True while a SOL turn is streaming in this renderer (any project). */
  streaming: boolean
  conversationByProject: Readonly<Record<string, string>>
  setStreaming: (streaming: boolean) => void
  setConversation: (projectId: string, conversationId: string) => void
  /** Forget a project's active conversation (SOLUSDEV-233 "new chat"). */
  clearConversation: (projectId: string) => void
  /** Clear per-account state on sign-out (SEC-M4). */
  resetForSignOut: () => void
}

export const SOL_SESSION_STORAGE_KEY = 'solus_sol_session_v1'
export const LEGACY_ORB_STORAGE_KEY = 'solus_orb_v1'

/** The active conversation for a project, or null. */
export const selectConversationId = (
  s: SolSessionState,
  projectId: string | null
): string | null => (projectId ? (s.conversationByProject[projectId] ?? null) : null)

/** The retired orbStore's persisted conversation map, or null when absent or
 *  malformed. ponytail: one-release migration — delete with the legacy key. */
export function readLegacyConversations(storage: Storage): Record<string, string> | null {
  try {
    const raw = storage.getItem(LEGACY_ORB_STORAGE_KEY)
    if (raw === null) return null
    const parsed: unknown = JSON.parse(raw)
    const state = (parsed as { state?: { conversationByProject?: unknown } } | null)?.state
    const map = state?.conversationByProject
    if (typeof map !== 'object' || map === null || Array.isArray(map)) return null
    const entries = Object.entries(map).filter(
      (entry): entry is [string, string] => typeof entry[1] === 'string'
    )
    return Object.fromEntries(entries)
  } catch {
    return null
  }
}

export const useSolSessionStore = create<SolSessionState>()(
  persist(
    (set) => ({
      streaming: false,
      conversationByProject: {},
      setStreaming: (streaming) => set({ streaming }),
      setConversation: (projectId, conversationId) =>
        set((s) => ({
          conversationByProject: { ...s.conversationByProject, [projectId]: conversationId }
        })),
      clearConversation: (projectId) =>
        set((s) => ({
          conversationByProject: Object.fromEntries(
            Object.entries(s.conversationByProject).filter(([key]) => key !== projectId)
          )
        })),
      resetForSignOut: () => set({ conversationByProject: {}, streaming: false })
    }),
    {
      name: SOL_SESSION_STORAGE_KEY,
      partialize: (s) => ({ conversationByProject: s.conversationByProject })
    }
  )
)

// One-time read of the legacy orb store so an upgrade keeps the open chats.
{
  const legacy = readLegacyConversations(localStorage)
  if (legacy !== null && localStorage.getItem(SOL_SESSION_STORAGE_KEY) === null) {
    useSolSessionStore.setState({ conversationByProject: legacy })
  }
  localStorage.removeItem(LEGACY_ORB_STORAGE_KEY)
}

/** Run `teardown` when the signed-in account ENDS: sign-out, or an in-place
 *  identity swap (OAuth loopback, magic link, another window) that never passes
 *  through 'unauthenticated' — so key on the identity, not the status
 *  (SOLUSDEV-233 security review H1). Shared by every per-account store. */
export function onAccountEnd(teardown: () => void): () => void {
  return useAuthStore.subscribe((state, prev) => {
    if (prev.status !== 'authenticated') return
    const signedOut = state.status === 'unauthenticated'
    const identitySwapped =
      state.status === 'authenticated' && state.user?.email !== prev.user?.email
    if (signedOut || identitySwapped) teardown()
  })
}

// SEC-M4: conversation ids are per-account and persisted, so an account switch
// must not leave the previous user's ids for a new token to request.
// Lane-owned subscription.
onAccountEnd(() => useSolSessionStore.getState().resetForSignOut())
