// SOLUSDEV-235 — the window title row. The renderer draws it (main collapses the
// native bar to the macOS traffic lights via `titleBarStyle: 'hiddenInset'`),
// so it doubles as the drag region and hosts the project pill. Controls inside
// it opt out of dragging with `.app-no-drag`.
import type { ReactNode } from 'react'
import { getDesktopPlatform } from '../../lib/desktopBridge'

export const TITLE_BAR_HEIGHT = 44
/** Room for the macOS traffic lights (x 16 + three 12px lights with 8px gaps). */
const MAC_TRAFFIC_LIGHT_INSET = 84
const PLAIN_INSET = 14

export function TitleBar({ children }: { children: ReactNode }): React.JSX.Element {
  const inset = getDesktopPlatform() === 'darwin' ? 'mac' : 'none'
  return (
    <div
      data-testid="title-bar"
      data-inset={inset}
      className="app-drag"
      style={{
        height: TITLE_BAR_HEIGHT,
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        paddingLeft: inset === 'mac' ? MAC_TRAFFIC_LIGHT_INSET : PLAIN_INSET,
        paddingRight: PLAIN_INSET,
        background: 'var(--bg)',
        borderBottom: '1px solid var(--bd)'
      }}
    >
      <div className="app-no-drag" style={{ display: 'inline-flex', alignItems: 'center' }}>
        {children}
      </div>
    </div>
  )
}
