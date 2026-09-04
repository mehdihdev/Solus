// SOLUSDEV-235 — the Store's NAVIGATION state only: which extension the detail
// page is showing. Install state lives on the server (docs/api/extensions.md
// §6) and is read through `useExtensions`; nothing here is persisted, so a
// sign-out (`reset`) or a project switch (`select(null)`) leaves no trace.
import { create } from 'zustand'

export interface ExtensionsState {
  /** Which extension the Store is showing in detail, or null for the catalog. */
  selectedId: string | null
  select: (extensionId: string | null) => void
  reset: () => void
}

export const useExtensionsStore = create<ExtensionsState>()((set) => ({
  selectedId: null,
  select: (selectedId) => set({ selectedId }),
  reset: () => set({ selectedId: null })
}))
