// Team switching — the ONE choke point (SOLUSDEV-244 / HOME H5).
//
// A team switch is a BROADER state swap than a project switch: the project
// list changes, and an open project that belongs to the previous team must not
// stay open under the new team's name with its focus cache, SOL session,
// extension selection and companion still bound to it. Before H5 the switch was
// `setTeamId(id)` in two hooks and nothing else.
//
// Rule: if the open project is not the target team's, close it THROUGH the
// project choke point (`switchWorkspaceProject(null)` clears every
// project-scoped store listed in projectSwitch.ts), then move the team. A
// project already in the target team stays open. `useHomeData` reloads the
// grid off the stored team id and blanks it while the new team loads.
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import { devBypassActive } from '../../lib/supabase'
import { postDataEvents } from '../../lib/api/resources.extensions'
import { switchWorkspaceProject, type SwitchSurface } from './projectSwitch'

/** Best-effort data event (ADR-011); never disturbs the switch. */
function reportTeamSwitch(
  from: string | null,
  to: string,
  closedProjectId: string | null,
  surface: SwitchSurface
): void {
  if (devBypassActive || useAuthStore.getState().status !== 'authenticated') return
  void postDataEvents([
    {
      event_type: 'team.switched',
      payload: { from_team_id: from, to_team_id: to, closed_project_id: closedProjectId, surface }
    }
  ]).catch(() => undefined)
}

/**
 * Make `teamId` the active team. Closes an open project that belongs to
 * another team (dropping everything scoped to it); leaves one that already
 * belongs to `teamId` open. Re-selecting the active team is a no-op.
 */
export function switchWorkspaceTeam(teamId: string, surface: SwitchSurface): void {
  const workspace = useWorkspaceStore.getState()
  const previousTeamId = workspace.teamId
  const open = workspace.project
  const closes = open !== null && open.teamId !== teamId
  if (!closes && previousTeamId === teamId) return
  if (closes) switchWorkspaceProject(null, surface)
  useWorkspaceStore.getState().setTeamId(teamId)
  reportTeamSwitch(previousTeamId, teamId, closes ? open.id : null, surface)
}
