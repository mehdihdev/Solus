// SOLUSDEV-327 — the menu bar's SOL control: the orb (mirroring SOL's state for the open
// project, also while the sidebar is closed), `SOL` and the ⌘J / Ctrl J hint. Hidden on the SOL
// page, which already is SOL.
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { isMac } from '../commandHotkey'
import { selectSession, useSolChatStore } from '../solChatStore'
import { toggleSidebar } from './sidebarActions'
import { sidebarShortcutHint } from './sidebarHotkey'
import { SolOrbDot } from './SidebarParts'
import { SOL_SIDEBAR_TOGGLE_ID } from './SolSidebarHost'
import { selectSidebarOpen, useSolSidebarStore } from './solSidebarStore'
import './solSidebar.css'

export function SolSidebarToggle({ screen }: { screen: string }): React.JSX.Element | null {
  const open = useSolSidebarStore((s) => selectSidebarOpen(s, screen))
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const working = useSolChatStore((s) => selectSession(s, projectId).streaming)
  if (screen === 'sol') return null
  const hint = sidebarShortcutHint(isMac())
  return (
    <button
      id={SOL_SIDEBAR_TOGGLE_ID}
      type="button"
      className="sol-sb-toggle interactive"
      aria-pressed={open}
      aria-label={`SOL sidebar (${hint})`}
      title={`${open ? 'Hide' : 'Show'} SOL beside this screen (${hint})`}
      onClick={() => toggleSidebar(screen, 'button')}
    >
      <SolOrbDot working={working} />
      SOL
      <span className="sol-sb-toggle-hint" aria-hidden="true">
        {hint}
      </span>
    </button>
  )
}
