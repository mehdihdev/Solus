// Machine-local project→folder links (SOLUSDEV-164). A working-copy path is
// specific to this computer (and often a private location), so it is persisted
// LOCALLY via localStorage and never sent to the Solus API. Keyed by project id.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

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
      setFolder: (projectId, link) =>
        set((s) => ({ folders: { ...s.folders, [projectId]: link } })),
      clearFolder: (projectId) =>
        set((s) => {
          const next = { ...s.folders }
          delete next[projectId]
          return { folders: next }
        })
    }),
    { name: PROJECT_FOLDER_STORAGE_KEY }
  )
)
