// SOLUSDEV-327 — `sol.sidebar_toggled` (sol-sidebar.md §7, API.md §2.13): what happened to the
// sidebar, on which screen, from which control — enums only. Best effort, like every client
// event: consent is gated server-side and a failed post is dropped.
import { postDataEvents } from '../../../lib/api/resources.extensions'
import { devBypassActive } from '../../../lib/supabase'
import { useAuthStore } from '../../../store/authStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'

export type SidebarAction = 'open' | 'close' | 'expand' | 'pop_out'
export type SidebarTrigger = 'button' | 'shortcut' | 'header' | 'escape'

export function reportSidebarToggled(
  action: SidebarAction,
  screen: string,
  via: SidebarTrigger
): void {
  if (devBypassActive || useAuthStore.getState().status !== 'authenticated') return
  const projectId = useWorkspaceStore.getState().project?.id
  void postDataEvents([
    {
      event_type: 'sol.sidebar_toggled',
      ...(projectId ? { project_id: projectId } : {}),
      payload: { action, screen, via }
    }
  ]).catch(() => undefined)
}
