// The shell's own screens: their labels and the rail items that open them. Pure data, so
// adding a screen is an edit here (plus its entry in the shell's screen table).
import { Icons } from '../../components/ui/icons.constants'
import type { MainScreen } from './shellStore'

/** Screen labels (the data-screen-label hook for tests; the topbar breadcrumb is gone — SOLUSDEV-235). */
export const SCREEN_TITLES: Readonly<Record<string, string>> = {
  home: 'Home',
  workspace: 'Workspace',
  hardware: 'Hardware',
  bench: 'Live Bench',
  sol: 'SOL',
  store: 'Store',
  billing: 'Billing',
  settings: 'Settings',
  alert: 'Alert',
  'ext-page': 'Extension'
}

export interface RailItem {
  screen: MainScreen
  icon: React.ReactNode
  label: string
  /** Drawn with an accent border + tint so it reads as the "add capability" action (SOLUSDEV-235). */
  emphasis?: boolean
}

/** Top rail: Home + the project-scoped screens in flow order. */
export const RAIL_TOP: readonly RailItem[] = [
  { screen: 'home', icon: <Icons.home size={17} />, label: 'Home' },
  { screen: 'workspace', icon: <Icons.graph size={17} />, label: 'Workspace' },
  { screen: 'hardware', icon: <Icons.hardware size={17} />, label: 'Hardware' },
  { screen: 'bench', icon: <Icons.bench size={17} />, label: 'Live Bench' },
  { screen: 'sol', icon: <Icons.sol size={17} />, label: 'SOL' }
]

/** SOLUSDEV-235: the Store — capabilities are installed, not built in. The
 *  installed extensions' tabs follow it behind a separator (STORE ST3). */
export const RAIL_STORE: RailItem = {
  screen: 'store',
  icon: <Icons.plus size={17} />,
  label: 'Store',
  emphasis: true
}

/** Bottom rail: account-level screens pinned below the spacer. */
export const RAIL_BOTTOM: readonly RailItem[] = [
  { screen: 'billing', icon: <Icons.card size={17} />, label: 'Billing' },
  { screen: 'settings', icon: <Icons.gear size={17} />, label: 'Settings' }
]

/** Whether a rail item is the active screen (Workspace also owns Alert). */
export function isRailActive(item: RailItem, name: string): boolean {
  return name === item.screen || (item.screen === 'workspace' && name === 'alert')
}
