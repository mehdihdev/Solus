// SOLUSDEV-317 — what opening a ⌘K result does. Every branch reuses the
// shell's existing path: screens and extension pages through the shell's
// navigation, projects and teams through their switch choke points (so every
// project-scoped store is swapped exactly as from Home), nodes through a jump
// request the Workspace screen serves with its own reveal.
import { useWorkspaceStore } from '../../store/workspaceStore'
import { switchWorkspaceProject } from '../workspace/projectSwitch'
import type { MainScreen } from '../workspace/shellStore'
import { switchWorkspaceTeam } from '../workspace/teamSwitch'
import type { PaletteTarget } from './paletteItems'
import { usePaletteStore } from './paletteStore'

export interface PaletteActions {
  go: (screen: MainScreen) => void
  openExtensionPage: (slug: string) => void
}

export function runPaletteTarget(target: PaletteTarget, actions: PaletteActions): void {
  switch (target.type) {
    case 'screen':
      actions.go(target.screen)
      return
    case 'extension':
      actions.openExtensionPage(target.slug)
      return
    case 'project':
      switchWorkspaceProject(target.project, 'palette')
      actions.go('workspace')
      return
    case 'team':
      switchWorkspaceTeam(target.teamId, 'palette')
      actions.go('home')
      return
    case 'node':
      // A node id means nothing outside its project; a stale pick must not jump.
      if (useWorkspaceStore.getState().project?.id !== target.projectId) return
      usePaletteStore.getState().requestJump(target.projectId, target.entityId)
      actions.go('workspace')
  }
}
