// SOLUSDEV-317 — ⌘K palette state: open/closed, the in-memory recents, and the
// graph-jump hand-off to the Workspace screen (command-palette.md).
//
// Recents are KEYS only, re-resolved against live items on every render, so a
// deleted project or node simply stops showing — the store never holds names.
// Not persisted (WS-01): a node key carries an entity id, and on a shared
// workstation the next user must not inherit where this one has been.
import { create } from 'zustand'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'

export const MAX_RECENTS = 8
/** How long a graph jump may wait for its graph to load before it is abandoned. */
export const JUMP_TTL_MS = 15_000

export interface GraphJump {
  projectId: string
  entityId: string
  /** Monotonic, so jumping to the same node twice is two requests. */
  sequence: number
  requestedAt: number
}

export interface PaletteState {
  open: boolean
  recentKeys: readonly string[]
  jump: GraphJump | null

  setOpen: (open: boolean) => void
  toggle: () => void
  remember: (key: string) => void
  requestJump: (projectId: string, entityId: string) => void
  consumeJump: (sequence: number) => void
  reset: () => void
}

const INITIAL = {
  open: false,
  recentKeys: [] as readonly string[],
  jump: null as GraphJump | null
}

export const usePaletteStore = create<PaletteState>((set) => ({
  ...INITIAL,

  setOpen: (open) => set({ open }),
  toggle: () => set((s) => ({ open: !s.open })),
  remember: (key) =>
    set((s) => ({
      recentKeys: [key, ...s.recentKeys.filter((k) => k !== key)].slice(0, MAX_RECENTS)
    })),
  requestJump: (projectId, entityId) =>
    set((s) => ({
      jump: {
        projectId,
        entityId,
        sequence: (s.jump?.sequence ?? 0) + 1,
        requestedAt: Date.now()
      }
    })),
  consumeJump: (sequence) => set((s) => (s.jump?.sequence === sequence ? { jump: null } : s)),
  reset: () => set({ ...INITIAL })
}))

// A node belongs to its project: switching projects drops node recents and any pending jump.
useWorkspaceStore.subscribe((next, previous) => {
  if (next.project?.id === previous.project?.id) return
  usePaletteStore.setState((s) => ({
    recentKeys: s.recentKeys.filter((key) => !key.startsWith('node:')),
    jump: null
  }))
})

// Another user (or none) means none of this is theirs to see.
useAuthStore.subscribe((next, previous) => {
  if (next.user?.email !== previous.user?.email || next.status !== previous.status)
    usePaletteStore.getState().reset()
})
