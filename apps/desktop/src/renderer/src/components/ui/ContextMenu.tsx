// Pointer-positioned right-click menu (SOLUSDEV-240). One implementation for
// every surface that offers actions on right-click: a fixed backdrop that
// closes on click, a `role="menu"` box clamped inside the viewport, and
// `role="menuitem"` buttons. Disabled items explain themselves with a hint.
import type { CSSProperties } from 'react'
import { Mono } from './Mono'

const DEFAULT_BOX = { width: 210, height: 130 }

/** Pointer coordinates clamped so a `size` box stays fully visible. */
export function clampMenuPosition(
  x: number,
  y: number,
  size: { width: number; height: number } = DEFAULT_BOX
): { x: number; y: number } {
  return {
    x: Math.max(0, Math.min(x, window.innerWidth - size.width)),
    y: Math.max(0, Math.min(y, window.innerHeight - size.height))
  }
}

export interface ContextMenuItem {
  label: string
  onSelect: () => void
  danger?: boolean
  disabled?: boolean
  /** Shown muted under a disabled item — why it cannot be picked right now. */
  hint?: string
}

export interface ContextMenuProps {
  x: number
  y: number
  /** Mono micro-label above the items (rendered upper-case). */
  title?: string
  items: readonly ContextMenuItem[]
  onClose: () => void
}

const ITEM_STYLE: CSSProperties = {
  display: 'block',
  width: '100%',
  textAlign: 'left',
  background: 'transparent',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
  fontFamily: 'var(--font-ui)',
  fontSize: 12.5,
  padding: '6px 9px'
}

export function ContextMenu({ x, y, title, items, onClose }: ContextMenuProps): React.JSX.Element {
  return (
    <>
      <div
        data-testid="context-menu-backdrop"
        style={{ position: 'fixed', inset: 0, zIndex: 60 }}
        onClick={onClose}
        onContextMenu={(e) => {
          e.preventDefault()
          onClose()
        }}
      />
      <div
        role="menu"
        className="popover-in"
        style={{
          position: 'fixed',
          left: x,
          top: y,
          zIndex: 61,
          minWidth: 200,
          padding: 5,
          background: 'var(--sur)',
          border: '1px solid var(--bd)',
          borderRadius: 6,
          boxShadow: '0 16px 44px rgba(0,0,0,0.5)'
        }}
      >
        {title && (
          <div style={{ padding: '3px 9px 6px' }}>
            <Mono size={7.5}>{title.toUpperCase()}</Mono>
          </div>
        )}
        {items.map((item) => (
          <button
            key={item.label}
            type="button"
            role="menuitem"
            className={item.disabled ? undefined : 'interactive'}
            aria-disabled={item.disabled ? 'true' : undefined}
            onClick={() => {
              if (item.disabled) return
              onClose()
              item.onSelect()
            }}
            style={{
              ...ITEM_STYLE,
              color: item.disabled ? 'var(--mut)' : item.danger ? 'var(--err)' : 'var(--tx)',
              cursor: item.disabled ? 'default' : 'pointer'
            }}
          >
            {item.label}
            {item.disabled && item.hint && (
              <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 2 }}>{item.hint}</div>
            )}
          </button>
        ))}
      </div>
    </>
  )
}
