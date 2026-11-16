// SOLUSDEV-327 — the sidebar's pieces: header (orb, tag, pop-out / expand / close), the empty
// state (context greeting + suggestion chips) and the left-edge resize handle.
import { Icons } from '../../../components/ui/icons.constants'
import { SIDEBAR_MAX_WIDTH, SIDEBAR_MIN_WIDTH } from './solSidebarStore'
import type { SidebarResize } from './sidebarHooks'

export function SolOrbDot({ working }: { working: boolean }): React.JSX.Element {
  return <span className={working ? 'sol-orb sol-pulse' : 'sol-orb'} aria-hidden="true" />
}

export interface SidebarHeaderProps {
  tag: string
  working: boolean
  /** Absent where there is no SOL window (outside Electron): the button is not drawn. */
  onPopOut?: () => void
  onExpand: () => void
  onClose: () => void
}

export function SidebarHeader({
  tag,
  working,
  onPopOut,
  onExpand,
  onClose
}: SidebarHeaderProps): React.JSX.Element {
  return (
    <div className="sol-sb-head">
      <SolOrbDot working={working} />
      <span className="sol-sb-title">SOL</span>
      <span className="sol-sb-tag" title={tag}>
        {tag}
      </span>
      <span style={{ flex: 1 }} />
      {onPopOut && (
        <HeaderButton label="Pop out to the pill" onClick={onPopOut}>
          <Icons.popOut size={15} />
        </HeaderButton>
      )}
      <HeaderButton label="Open in the SOL page" onClick={onExpand}>
        <Icons.expand size={15} />
      </HeaderButton>
      <HeaderButton label="Close SOL sidebar" onClick={onClose}>
        <Icons.x size={14} />
      </HeaderButton>
    </div>
  )
}

function HeaderButton({
  label,
  onClick,
  children
}: {
  label: string
  onClick: () => void
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <button
      type="button"
      className="sol-sb-icon"
      aria-label={label}
      title={label}
      onClick={onClick}
    >
      {children}
    </button>
  )
}

/** An empty conversation: SOL's first line for this screen, then its starting questions. */
export function SidebarGreeting({
  greeting,
  suggestions,
  onAsk
}: {
  greeting: string
  suggestions: readonly string[]
  onAsk: (text: string) => void
}): React.JSX.Element {
  return (
    <div className="sol-sb-empty">
      <div className="sol-sb-greeting">{greeting}</div>
      {suggestions.length > 0 && (
        <div className="sol-sb-chips">
          {suggestions.map((text) => (
            <button key={text} type="button" className="sol-sb-chip" onClick={() => onAsk(text)}>
              {text}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function ResizeHandle({ resize }: { resize: SidebarResize }): React.JSX.Element {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize SOL sidebar"
      aria-valuemin={SIDEBAR_MIN_WIDTH}
      aria-valuemax={SIDEBAR_MAX_WIDTH}
      aria-valuenow={resize.width}
      tabIndex={0}
      className="sol-sb-resize"
      onPointerDown={resize.onPointerDown}
      onKeyDown={resize.onKeyDown}
    />
  )
}
