// SOLUSDEV-235 — what the project menu bar contains. Pure data: every item is
// an existing screen, an existing action, or an https link, so reshaping a menu
// is an edit here and nowhere else. Contents are a placeholder pending a design
// (see docs/wireflows/project-topbar.md).
import type { MainScreen } from './shellStore'

export interface MenuLinkItem {
  readonly label: string
  /** https only — main's window-open guard drops anything else. */
  readonly href: string
}
export interface MenuScreenItem {
  readonly label: string
  readonly screen: MainScreen
  /** Disabled until a project is open. */
  readonly projectScoped?: boolean
}
export interface MenuActionItem {
  readonly label: string
  readonly action: 'sign_out'
}
export type MenuItem = MenuLinkItem | MenuScreenItem | MenuActionItem | 'separator'

export interface MenuSpec {
  readonly id: string
  readonly label: string
  readonly items: readonly MenuItem[]
  /** Shown above the items while no project is open (project-scoped menus). */
  readonly projectHint?: string
}

export const MENU_BAR_HEIGHT = 40

export const MENUS: readonly MenuSpec[] = [
  {
    id: 'solus',
    label: 'Solus',
    items: [
      { label: 'Home', screen: 'home' },
      { label: 'Settings', screen: 'settings' },
      { label: 'Billing', screen: 'billing' },
      'separator',
      { label: 'Sign out', action: 'sign_out' }
    ]
  },
  {
    id: 'view',
    label: 'View',
    items: [
      { label: 'Overview', screen: 'overview' },
      { label: 'Workspace', screen: 'workspace' },
      { label: 'Sources', screen: 'sources' },
      { label: 'Live Bench', screen: 'bench' },
      { label: 'SOL', screen: 'sol' },
      { label: 'Store', screen: 'store' }
    ]
  },
  {
    id: 'robot',
    label: 'Robot',
    projectHint: 'Open a project to act on its robot.',
    items: [
      { label: 'Project overview', screen: 'overview', projectScoped: true },
      { label: 'Connect a tool…', screen: 'sources', projectScoped: true },
      { label: 'Connect a device…', screen: 'bench', projectScoped: true },
      { label: 'Ask SOL', screen: 'sol', projectScoped: true }
    ]
  },
  {
    id: 'help',
    label: 'Help',
    items: [
      { label: 'Documentation', href: 'https://docs.solusforge.com' },
      { label: 'Report an issue', href: 'https://gitlab.com/solusforge/solus/-/issues' }
    ]
  }
]
