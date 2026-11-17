// SOLUSDEV-233: a reply that finishes while nobody is looking raises the shell toast. Split from
// solChatStore.ts (which owns the turn) so "who is watching" is one small rule.
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useShellStore } from '../workspace/shellStore'
import { selectSidebarOpen, useSolSidebarStore } from './sidebar/solSidebarStore'

/** True when the user is looking at THIS project's SOL thread right now: on the SOL page, or with
 *  the SOL sidebar open on the current screen (it shows the same chat). */
export function userIsWatching(projectId: string): boolean {
  const screen = useShellStore.getState().lastMain
  const currentProject = useWorkspaceStore.getState().project?.id ?? null
  const looking = screen === 'sol' || selectSidebarOpen(useSolSidebarStore.getState(), screen)
  return looking && currentProject === projectId
}

/** A backgrounded reply finished (or failed): raise the shell toast. The View
 *  action is offered only when the workspace is still on the turn's project. */
export function notifyAway(projectId: string, prompt: string, failed: boolean): void {
  if (userIsWatching(projectId)) return
  const sameProject = useWorkspaceStore.getState().project?.id === projectId
  useShellStore.getState().setToast({
    kind: failed ? 'warn' : 'ok',
    title: failed ? 'SOL turn failed' : 'SOL replied',
    // Another project's prompt is that project's business (SOLUSDEV-242): the
    // toast names the fact, not the text, when the user has moved on.
    body: sameProject
      ? `“${prompt.slice(0, 60)}${prompt.length > 60 ? '…' : ''}” — open SOL to read it.`
      : 'A turn finished in another project — switch back to read it.',
    ...(sameProject ? { action: 'View', screen: 'sol' as const } : {})
  })
}
