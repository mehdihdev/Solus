// SOLUSDEV-327 — every way the sidebar opens or closes goes through here, so the store and the
// `sol.sidebar_toggled` event never disagree. `screen` is where it happened (for the event).
import { reportSidebarToggled, type SidebarAction, type SidebarTrigger } from './sidebarEvents'
import { selectSidebarOpen, useSolSidebarStore } from './solSidebarStore'

/** Flip the sidebar from `screen`; returns whether it is now open. Inert on the SOL page. */
export function toggleSidebar(screen: string, via: SidebarTrigger): boolean {
  if (screen === 'sol') return false
  const store = useSolSidebarStore.getState()
  const next = !selectSidebarOpen(store, screen)
  store.setOpen(next)
  reportSidebarToggled(next ? 'open' : 'close', screen, via)
  return next
}

/** Close the sidebar from `screen` as the result of `action` (close, expand or pop out). */
export function closeSidebar(
  screen: string,
  via: SidebarTrigger,
  action: Exclude<SidebarAction, 'open'> = 'close'
): void {
  useSolSidebarStore.getState().setOpen(false)
  reportSidebarToggled(action, screen, via)
}
