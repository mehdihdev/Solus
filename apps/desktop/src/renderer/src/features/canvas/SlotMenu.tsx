// SOLUSDEV-235 / EXT-15 — the slot's `▭ ▾` menu: size (gated by the widget's
// minimum), then move left/right. Keyboard-first — reordering has no drag in
// this build (wireflow "Grid and slots").
import { useEffect, useRef, useState } from 'react'
import type { WidgetSizeHint, WidgetSlotSize } from '@solus/shared-types'
import { Icons } from '../../components/ui/icons.constants'
import { SLOT_SIZES, allowedSizes } from './layout'

export interface SlotMenuProps {
  readonly title: string
  readonly size: WidgetSlotSize
  readonly hint: WidgetSizeHint | undefined
  readonly canMoveLeft: boolean
  readonly canMoveRight: boolean
  readonly onResize: (size: WidgetSlotSize) => void
  readonly onMove: (direction: -1 | 1) => void
}

export const TOO_SMALL = 'Too small for this widget'

const SIZE_LABEL: Readonly<Record<WidgetSlotSize, string>> = {
  compact: 'Compact',
  standard: 'Standard',
  wide: 'Wide',
  full: 'Full'
}

const TRIGGER_STYLE: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 2,
  padding: '3px 5px',
  background: 'transparent',
  border: '1px solid transparent',
  borderRadius: 3,
  color: 'var(--mut)',
  cursor: 'pointer'
}

/** Close on Escape and on any pointer press outside the menu. */
function useDismiss(
  open: boolean,
  root: React.RefObject<HTMLElement | null>,
  close: () => void
): void {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') close()
    }
    const onPress = (e: MouseEvent): void => {
      if (root.current && !root.current.contains(e.target as Node)) close()
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onPress)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onPress)
    }
  }, [open, root, close])
}

export function SlotMenu(props: SlotMenuProps): React.JSX.Element {
  const { title, size, hint, canMoveLeft, canMoveRight, onResize, onMove } = props
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLSpanElement | null>(null)
  const close = (): void => setOpen(false)
  useDismiss(open, rootRef, close)
  const allowed = allowedSizes(hint)

  const pick = (next: WidgetSlotSize): void => {
    onResize(next)
    close()
  }
  const move = (direction: -1 | 1): void => {
    onMove(direction)
    close()
  }

  return (
    <span ref={rootRef} style={{ position: 'relative', display: 'inline-flex' }}>
      <button
        type="button"
        className="interactive"
        style={TRIGGER_STYLE}
        aria-label={`${title} slot options`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <Icons.card size={13} />
        <span aria-hidden="true" style={{ fontSize: 9 }}>
          ▾
        </span>
      </button>
      {open && (
        <div
          role="menu"
          aria-label={`${title} slot options`}
          className="widget-slot-menu popover-in"
        >
          {SLOT_SIZES.map((option) => {
            const enabled = allowed.includes(option)
            return (
              <button
                key={option}
                type="button"
                role="menuitemradio"
                aria-checked={option === size}
                disabled={!enabled}
                title={enabled ? undefined : TOO_SMALL}
                onClick={() => pick(option)}
              >
                <span>{SIZE_LABEL[option]}</span>
                {option === size && <Icons.check size={12} />}
              </button>
            )
          })}
          <hr />
          <button type="button" role="menuitem" disabled={!canMoveLeft} onClick={() => move(-1)}>
            Move left
          </button>
          <button type="button" role="menuitem" disabled={!canMoveRight} onClick={() => move(1)}>
            Move right
          </button>
        </div>
      )}
    </span>
  )
}
