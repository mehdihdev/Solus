// SOLUSDEV-327 — every way the sidebar opens or closes goes through here, so the store and the
// `sol.sidebar_toggled` event never disagree.
import { reportSidebarToggled, type SidebarAction, type SidebarTrigger } from './sidebarEvents'
import { selectSidebarOpen, useSolSidebarStore } from './solSidebarStore'

/** Flip the sidebar for `key`; returns whether it is now open. The SOL page never opens it. */
export function toggleSidebar(key: string, via: SidebarTrigger): boolean {
  if (key === 'sol') return false
  const store = useSolSidebarStore.getState()
  const next = !selectSidebarOpen(store, key)
  store.setOpen(key, next)
  reportSidebarToggled(next ? 'open' : 'close', key, via)
  return next
}

/** Close the sidebar for `key` as the result of `action` (close, expand or pop out). */
export function closeSidebar(
  key: string,
  via: SidebarTrigger,
  action: Exclude<SidebarAction, 'open'> = 'close'
): void {
  useSolSidebarStore.getState().setOpen(key, false)
  reportSidebarToggled(action, key, via)
}
