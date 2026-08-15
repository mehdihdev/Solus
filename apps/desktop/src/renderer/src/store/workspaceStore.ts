// Workspace context resolved from the API during onboarding: the team the
// project lives under and the created project. Persisted so the workspace home
// can re-fetch on reload. `linked` records whether we actually reached the API
// (vs the offline/dev-bypass simulated path).
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { getDesktopCompanionBridge } from '../lib/desktopBridge'

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

/**
 * Tell the local companion which project it serves (SOLUSDEV-154 / BRG-04).
 *
 * The single choke point for project changes, mirroring how `authStore`
 * relays the access token. The companion's bridge URL is project-scoped
 * (`/api/v1/projects/{id}/bridge`) and fixed in its environment at spawn, so
 * main respawns it on change. Nothing relayed this before, so the companion
 * dialled a project-less URL that matched no route and the API answered 403
 * on every retry.
 *
 * Fire-and-forget, and null outside Electron (static preview) so the store
 * stays usable without a desktop bridge.
 */
function relayProject(projectId: string | null): void {
  void getDesktopCompanionBridge()
    ?.setProject(projectId)
    .catch(() => undefined)
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set) => ({
      teamId: null,
      project: null,
      linked: false,
      setTeamId: (teamId) => set({ teamId }),
      setProject: (project) => {
        set({ project })
        relayProject(project?.id ?? null)
      },
      setLinked: (linked) => set({ linked }),
      reset: () => {
        set({ teamId: null, project: null, linked: false })
        relayProject(null)
      }
    }),
    {
      name: WORKSPACE_STORAGE_KEY,
      // Rehydration sets state DIRECTLY — `persist` never calls the actions
      // above. Without this, opening the app with a project already stored (the
      // normal case) relayed nothing: main never learned the project, so the
      // companion was never spawned and the pill read "Bridge offline" until
      // the user manually switched projects. This is the startup half of the
      // relay; `setProject` is the in-session half.
      onRehydrateStorage: () => (state) => relayProject(state?.project?.id ?? null)
    }
  )
)
