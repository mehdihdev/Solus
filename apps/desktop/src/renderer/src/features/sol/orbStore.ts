// SOLX-02 (SOLUSDEV-201): state for the persistent SOL orb — dock corner,
// expanded chat panel, detached always-on-top window flag, the active
// conversation per project, and the streaming pulse. Zustand + immutable
// updates, pure selectors exported for testing (onboardingStore idiom).
//
// Persistence: dock/expand/conversation prefs only (settingsStore persist
// idiom). The detached #/orb window is a SEPARATE renderer process sharing
// localStorage, so persisting the conversation map lets it rehydrate into the
// same conversation. Runtime flags (streaming, detached) are per-window truth
// and never persist.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { useAuthStore } from '../../store/authStore'

export type OrbCorner = 'tl' | 'tr' | 'bl' | 'br'

export interface OrbState {
  corner: OrbCorner
  expanded: boolean
  /** True while the orb lives in the always-on-top window (this renderer's view). */
  detached: boolean
  /** True while a SOL turn is streaming — drives the orb pulse. */
  streaming: boolean
  conversationByProject: Readonly<Record<string, string>>
  setCorner: (corner: OrbCorner) => void
  setExpanded: (expanded: boolean) => void
  toggleExpanded: () => void
  setDetached: (detached: boolean) => void
  setStreaming: (streaming: boolean) => void
  setConversation: (projectId: string, conversationId: string) => void
  /** Forget a project's active conversation (SOLUSDEV-233 "new chat"). */
  clearConversation: (projectId: string) => void
  /** Clear per-account state on sign-out (SEC-M4). */
  resetForSignOut: () => void
}

export const ORB_STORAGE_KEY = 'solus_orb_v1'

/** Whether the orb should pulse (streaming/thinking only — idle costs ~0). */
export const selectOrbPulse = (s: OrbState): boolean => s.streaming

/** Nearest corner by window midpoints — corner snapping, not free placement. */
export function cornerFor(x: number, y: number, width: number, height: number): OrbCorner {
  return `${y < height / 2 ? 't' : 'b'}${x < width / 2 ? 'l' : 'r'}` as OrbCorner
}

/** The active conversation for a project, or null. */
export const selectConversationId = (s: OrbState, projectId: string | null): string | null =>
  projectId ? (s.conversationByProject[projectId] ?? null) : null

export const useOrbStore = create<OrbState>()(
  persist(
    (set) => ({
      corner: 'br',
      expanded: false,
      detached: false,
      streaming: false,
      conversationByProject: {},
      setCorner: (corner) => set({ corner }),
      setExpanded: (expanded) => set({ expanded }),
      toggleExpanded: () => set((s) => ({ expanded: !s.expanded })),
      setDetached: (detached) => set({ detached }),
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
      // SEC-M4: conversation ids are per-account. An account switch must not
      // leave the previous user's ids for the new token to request.
      resetForSignOut: () =>
        set(() => ({
          conversationByProject: {},
          expanded: false,
          streaming: false,
          detached: false
        }))
    }),
    {
      name: ORB_STORAGE_KEY,
      partialize: (s) => ({
        corner: s.corner,
        expanded: s.expanded,
        conversationByProject: s.conversationByProject
      })
    }
  )
)

// SEC-M4: conversation ids are per-account and persisted, so an account switch
// must not leave the previous user's ids for a new token to request — and an
// in-place identity swap (OAuth loopback, magic link, another window) never
// passes through 'unauthenticated', so key on the identity, not the status
// (SOLUSDEV-233 security review H1). Lane-owned subscription.
useAuthStore.subscribe((state, prev) => {
  if (prev.status !== 'authenticated') return
  const signedOut = state.status === 'unauthenticated'
  const identitySwapped =
    state.status === 'authenticated' && state.user?.email !== prev.user?.email
  if (signedOut || identitySwapped) {
    useOrbStore.getState().resetForSignOut()
  }
})
