// SOLUSDEV-246 / STORE ST3 — "Pin for all projects". The user's pinned
// extensions (docs/api/extensions.md §6.5): account state the server holds,
// mirrored here so the rail, the Store detail and the context menu read one
// answer. Pinning installs nothing — a pinned tab in a project where the bundle
// is not installed opens an honest "not installed here" state. Never persisted
// locally: a sign-out (`reset`) leaves nothing of this user on the workstation.
import { create } from 'zustand'
import {
  listExtensionPins,
  pinExtension,
  unpinExtension,
  type ExtensionPinApi
} from '../../lib/api/resources.extensions'

export type PinsStatus = 'idle' | 'loading' | 'ready' | 'offline'

export interface PinsState {
  status: PinsStatus
  pins: readonly ExtensionPinApi[]
  /** Read the server list; a failure keeps what is on screen (offline only when empty). */
  hydrate: () => Promise<void>
  pin: (slug: string) => Promise<boolean>
  unpin: (slug: string) => Promise<boolean>
  isPinned: (slug: string) => boolean
  reset: () => void
}

const INITIAL = { status: 'idle' as PinsStatus, pins: [] as readonly ExtensionPinApi[] }

export const usePinsStore = create<PinsState>()((set, get) => ({
  ...INITIAL,

  hydrate: async () => {
    if (get().status === 'idle') set({ status: 'loading' })
    try {
      const pins = await listExtensionPins()
      set({ status: 'ready', pins })
    } catch {
      set((s) => ({ status: s.pins.length > 0 ? 'ready' : 'offline' }))
    }
  },

  pin: async (slug) => {
    try {
      const row = await pinExtension(slug)
      set((s) => ({
        status: 'ready',
        pins: [...s.pins.filter((p) => p.slug !== row.slug), row]
      }))
      return true
    } catch {
      return false
    }
  },

  unpin: async (slug) => {
    try {
      await unpinExtension(slug)
      set((s) => ({ pins: s.pins.filter((p) => p.slug !== slug) }))
      return true
    } catch {
      return false
    }
  },

  isPinned: (slug) => get().pins.some((p) => p.slug === slug),

  reset: () => set({ ...INITIAL })
}))
