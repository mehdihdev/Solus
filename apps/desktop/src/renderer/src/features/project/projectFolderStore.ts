// Machine-local project→folder links (SOLUSDEV-164). A working-copy path is
// specific to this computer (and often a private location), so it never leaves
// this machine: only the co-located local API receives it (as `repo_root` on
// hardware propose/confirm), and only for the project it is linked to — the
// API confines it to this registry's entry for that project (recorded in
// docs/api/hardware.md §4). Keyed by project id.
//
// SOLUSDEV-166 (ADR-034): this store is now the DISPLAY CACHE. The durable,
// main-process-readable copy is ~/.solus/projects.json — that is what the
// companion's SOLUS_COMPANION_WORKSPACE derives from at spawn, so a link that
// only lived in localStorage kept the Altium fork failing closed. Mutations
// await the native registry acknowledgement before publishing the link. Failed
// writes leave the display cache unchanged; hydration
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
  setFolder: (projectId: string, link: FolderLink) => Promise<boolean>
  clearFolder: (projectId: string) => void
}

export const PROJECT_FOLDER_STORAGE_KEY = 'solus_project_folders_v1'

const pendingLinks = new Map<string, symbol>()

export const useProjectFolderStore = create<ProjectFolderState>()(
  persist(
    (set) => ({
      folders: {},
      setFolder: async (projectId, link) => {
        const bridge = getDesktopFolderBridge()
        if (!bridge) return false
        const attempt = Symbol()
        pendingLinks.set(projectId, attempt)
        try {
          const result = await bridge.link(projectId, link)
          if (result.ok !== true || pendingLinks.get(projectId) !== attempt) return false
          set((s) => ({ folders: { ...s.folders, [projectId]: link } }))
          return true
        } catch {
          return false
        } finally {
          if (pendingLinks.get(projectId) === attempt) pendingLinks.delete(projectId)
        }
      },
      clearFolder: (projectId) => {
        pendingLinks.delete(projectId)
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
