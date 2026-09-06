// Project switching — the ONE choke point (SOLUSDEV-242 / HOME H1).
//
// Switching projects must swap every piece of project-scoped state with
// nothing carried across. A parked SOL confirmation once followed the user
// into another project because the switch was three call sites, each clearing
// what its author remembered. Every switch — Home, the topbar switcher, the
// Team screen, and the dead-project validator — now goes through here.
//
// Store audit (what carries project state, and how it is kept honest):
//
//   workspaceStore   the switch itself; `teamId` follows the project's team
//   focusStore       keyed `${projectId}:${entityId}@depth` AND cleared here
//   solChatStore     sessions keyed by project (a turn in A keeps streaming in
//                    the background by design — SOLUSDEV-233 — but A's
//                    transcript, confirmations included, is never selected
//                    for B); the away-toast is cleared here on switch
//   orbStore         `conversationByProject` keyed by project
//   extensionsStore  Store detail selection cleared here (EXT-14)
//   shellStore       toast cleared here (a "SOL replied — View" raised by A
//                    must not open B's SOL page); detail routes reset by the
//                    shell (`alert`, `ext-page` → Overview)
//   retained graph   keyed by project id in useWorkspaceGraph (cleared on sign-out by the shell)
//   projectFolderStore, solCache (~/.solus), companion — keyed by project id;
//                    main respawns the companion on the relay in `setProject`
//   per-screen hooks (overview, sources, graph summary, widgets, bench) —
//                    keyed on `project.id` with stale-response guards
//
// Anything new that holds project data belongs in this table and, unless it is
// keyed by project id, in the clear list below. `projectSwitch.test.ts` drives
// every store through a switch.
import { useWorkspaceStore, type WorkspaceProject } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import { devBypassActive } from '../../lib/supabase'
import { postDataEvents } from '../../lib/api/resources.extensions'
import { useExtensionsStore } from '../extensions/extensionsStore'
import { useFocusStore } from './focusStore'
import { useShellStore } from './shellStore'

/** Where the switch came from — recorded on the data event (ADR-011). */
export type SwitchSurface = 'home' | 'topbar' | 'team' | 'validation' | 'onboarding' | 'overview'

/** Data-collection event, best effort: consent is gated server-side and a
 *  failed post never disturbs the switch. Skipped for the dev bypass — its
 *  fake session reads `authenticated` but carries no token the API accepts —
 *  and for a switch to no project. */
function reportSwitch(
  next: WorkspaceProject,
  previousId: string | null,
  surface: SwitchSurface
): void {
  if (devBypassActive || useAuthStore.getState().status !== 'authenticated') return
  void postDataEvents([
    {
      event_type: 'project.switched',
      project_id: next.id,
      payload: { from_project_id: previousId, surface }
    }
  ]).catch(() => undefined)
}

/**
 * Make `next` the open project (null ⇒ none), dropping everything scoped to
 * the previous one. Re-selecting the current project only refreshes its name
 * and team — it is not a switch and clears nothing.
 */
export function switchWorkspaceProject(
  next: WorkspaceProject | null,
  surface: SwitchSurface
): void {
  const workspace = useWorkspaceStore.getState()
  const previousId = workspace.project?.id ?? null
  workspace.setProject(next)
  if (next?.teamId) workspace.setTeamId(next.teamId)
  if (next !== null && next.id === previousId) return

  useFocusStore.getState().clearProject()
  useExtensionsStore.getState().select(null)
  useShellStore.getState().clearToast()
  if (next) reportSwitch(next, previousId, surface)
}

/**
 * The open project was renamed: keep the pill and switcher in step WITHOUT
 * dropping its team — the one non-switch write, still through the choke point
 * so nothing is cleared and nothing is reported.
 */
export function renameWorkspaceProject(name: string): void {
  const current = useWorkspaceStore.getState().project
  if (!current) return
  switchWorkspaceProject({ ...current, name }, 'overview')
}
