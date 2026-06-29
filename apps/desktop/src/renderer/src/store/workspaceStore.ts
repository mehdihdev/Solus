// Workspace context resolved from the API during onboarding: the team the
// project lives under and the created project. Persisted so the workspace home
// can re-fetch on reload. `linked` records whether we actually reached the API
// (vs the offline/dev-bypass simulated path).
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface WorkspaceProject {
  id: string
  name: string
}

export interface WorkspaceState {
  teamId: string | null
  project: WorkspaceProject | null
  linked: boolean
  setTeamId: (teamId: string | null) => void
  setProject: (project: WorkspaceProject | null) => void
  setLinked: (linked: boolean) => void
  reset: () => void
}

export const WORKSPACE_STORAGE_KEY = 'solus_workspace_v1'

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set) => ({
      teamId: null,
      project: null,
      linked: false,
      setTeamId: (teamId) => set({ teamId }),
      setProject: (project) => set({ project }),
      setLinked: (linked) => set({ linked }),
      reset: () => set({ teamId: null, project: null, linked: false })
    }),
    { name: WORKSPACE_STORAGE_KEY }
  )
)
