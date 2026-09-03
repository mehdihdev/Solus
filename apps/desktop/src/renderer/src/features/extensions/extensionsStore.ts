// SOLUSDEV-235 — per-project extension install state, kept locally until the
// Store backend exists. Keyed by project id so two projects never share an
// install (the same isolation the server will enforce per team/project).
// Persisted to localStorage like settingsStore; the backend hook will replace
// the persistence, not the shape. Updates are immutable (spread, never mutate).
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ExtensionInstallState, ExtensionManifest, RunFrequency } from './extension.types'
import { initialInstallState } from './extensionLogic'

export const EXTENSIONS_STORAGE_KEY = 'solus_extensions_v1'

type ProjectStates = Readonly<Record<string, ExtensionInstallState>>

export interface ExtensionsState {
  /** projectId → extensionId → state. Only touched extensions appear. */
  byProject: Readonly<Record<string, ProjectStates>>
  /** Which extension the Store is showing in detail, or null for the catalog. */
  selectedId: string | null

  select: (extensionId: string | null) => void
  install: (projectId: string, manifest: ExtensionManifest) => void
  uninstall: (projectId: string, manifest: ExtensionManifest) => void
  setEnabled: (projectId: string, manifest: ExtensionManifest, enabled: boolean) => void
  setRunFrequency: (projectId: string, manifest: ExtensionManifest, freq: RunFrequency) => void
  reset: () => void
}

const INITIAL = {
  byProject: {} as Readonly<Record<string, ProjectStates>>,
  selectedId: null as string | null
}

/** Pure selector: the state for one extension in one project, defaulting from the manifest. */
export function selectInstallState(
  byProject: Readonly<Record<string, ProjectStates>>,
  projectId: string,
  manifest: ExtensionManifest
): ExtensionInstallState {
  return byProject[projectId]?.[manifest.id] ?? initialInstallState(manifest)
}

function patch(
  byProject: Readonly<Record<string, ProjectStates>>,
  projectId: string,
  manifest: ExtensionManifest,
  change: Partial<ExtensionInstallState>
): Readonly<Record<string, ProjectStates>> {
  const current = selectInstallState(byProject, projectId, manifest)
  return {
    ...byProject,
    [projectId]: { ...(byProject[projectId] ?? {}), [manifest.id]: { ...current, ...change } }
  }
}

export const useExtensionsStore = create<ExtensionsState>()(
  persist(
    (set) => ({
      ...INITIAL,

      select: (selectedId) => set({ selectedId }),
      install: (projectId, manifest) =>
        set((s) => ({
          byProject: patch(s.byProject, projectId, manifest, { installed: true, enabled: true })
        })),
      uninstall: (projectId, manifest) =>
        set((s) => ({ byProject: patch(s.byProject, projectId, manifest, { installed: false }) })),
      setEnabled: (projectId, manifest, enabled) =>
        set((s) => ({ byProject: patch(s.byProject, projectId, manifest, { enabled }) })),
      setRunFrequency: (projectId, manifest, runFrequency) =>
        set((s) => ({ byProject: patch(s.byProject, projectId, manifest, { runFrequency }) })),
      reset: () => set({ ...INITIAL })
    }),
    {
      name: EXTENSIONS_STORAGE_KEY,
      // The selected extension is navigation, not preference — never persisted.
      partialize: (s) => ({ byProject: s.byProject })
    }
  )
)
