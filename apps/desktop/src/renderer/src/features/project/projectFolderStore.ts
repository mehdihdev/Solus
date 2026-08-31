// Machine-local project→folder links (SOLUSDEV-164). A working-copy path is
// specific to this computer (and often a private location), so it never goes
// to the Solus API. Keyed by project id.
//
// SOLUSDEV-166 (ADR-034): this store is now the DISPLAY CACHE. The durable,
// main-process-readable copy is ~/.solus/projects.json — that is what the
// companion's SOLUS_COMPANION_WORKSPACE derives from at spawn, so a link that
// only lived in localStorage kept the Altium fork failing closed. Mutations
// write through to the registry over IPC (fire-and-forget: the UI keeps its
// optimistic value and the main process logs registry failures); hydration
// merges the registry back into the cache at startup, registry winning.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { getDesktopFolderBridge } from '../../lib/desktopBridge'

export interface FolderLink {
  path: string
  /** The repo it was cloned from, when linked via clone (informational). */
  repoUrl?: string
}

export interface ProjectFolderState {
  folders: Record<string, FolderLink>
  setFolder: (projectId: string, link: FolderLink) => void
  clearFolder: (projectId: string) => void
}

export const PROJECT_FOLDER_STORAGE_KEY = 'solus_project_folders_v1'

export const useProjectFolderStore = create<ProjectFolderState>()(
  persist(
    (set) => ({
      folders: {},
      setFolder: (projectId, link) => {
        set((s) => ({ folders: { ...s.folders, [projectId]: link } }))
        void getDesktopFolderBridge()
          ?.link(projectId, link)
          .catch(() => undefined)
      },
      clearFolder: (projectId) => {
        set((s) => {
          const next = { ...s.folders }
          delete next[projectId]
          return { folders: next }
        })
        void getDesktopFolderBridge()
          ?.unlink(projectId)
          .catch(() => undefined)
      }
    }),
    { name: PROJECT_FOLDER_STORAGE_KEY }
  )
)

/**
 * Merge the machine registry into the display cache (registry wins) — the
 * localStorage copy can be cleared or stale while ~/.solus persists. No-op
 * outside the desktop app; a failing bridge leaves the cache standing.
 */
export async function hydrateProjectFolders(): Promise<void> {
  const bridge = getDesktopFolderBridge()
  if (!bridge) return
  try {
    const links = await bridge.links()
    const fromRegistry: Record<string, FolderLink> = {}
    for (const [projectId, entry] of Object.entries(links)) {
      fromRegistry[projectId] = {
        path: entry.path,
        ...(entry.repoUrl !== undefined ? { repoUrl: entry.repoUrl } : {})
      }
    }
    useProjectFolderStore.setState((s) => ({ folders: { ...s.folders, ...fromRegistry } }))
  } catch {
    /* registry unavailable — the cached view stands */
  }
}

// Reconcile once at startup (module load). Null bridge (browser preview,
// tests) makes this a no-op.
void hydrateProjectFolders()
