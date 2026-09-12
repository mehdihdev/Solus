import { useCallback, useEffect, useRef, useState } from 'react'
import type { Entity } from '../../../lib/api/resources'
import { useSettingsStore } from '../../../store/settingsStore'

const LINES = {
  Guide: [
    'Hover a card and scroll in to open it · scroll out to go back',
    'Double-click or → enters · ← goes back · Escape clears',
    'Drag a card anywhere; positions are shared with your team',
    'Add (top-left) brings in integrations and hardware'
  ],
  Expert: [
    'Scroll in opens · scroll out goes back',
    'Double-click / → enters · ← back · Escape clears',
    'Drag cards; positions are team-shared',
    'Add (top-left): integrations and hardware'
  ]
} as const

interface HelpPopoverProps {
  trail: readonly Entity[]
  onOverview: () => void
}

/** The `?` corner button; the popover is the only place the trail text appears. */
export function HelpPopover({ trail, onOverview }: HelpPopoverProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const close = useCallback(() => setOpen(false), [])
  const anchor = useRef<HTMLDivElement>(null)
  const mode = useSettingsStore((state) => state.solMode)
  useHelpDismiss(open, anchor, close)
  return (
    <div className="graph-help" ref={anchor}>
      <button type="button" aria-label="Help" aria-expanded={open} onClick={() => setOpen(!open)}>
        ?
      </button>
      {open && (
        <div role="dialog" aria-label="Workspace help" className="workspace-add-panel">
          <header>
            <strong>Workspace help</strong>
            <button type="button" aria-label="Close help" onClick={close}>
              ×
            </button>
          </header>
          <ul>
            {LINES[mode].map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <p className="graph-help-trail">{['Project', ...trail.map((e) => e.name)].join(' › ')}</p>
          <button
            type="button"
            aria-label="Project overview"
            disabled={trail.length === 0}
            onClick={() => {
              onOverview()
              close()
            }}
          >
            Project overview
          </button>
        </div>
      )}
    </div>
  )
}

// Same dismissal as WorkspaceAdd's useAddDismiss; kept local so the two popovers stay independent.
function useHelpDismiss(
  open: boolean,
  anchor: React.RefObject<HTMLDivElement | null>,
  close: () => void
): void {
  useEffect(() => {
    if (!open) return
    const key = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        close()
      }
    }
    const outside = (event: PointerEvent): void => {
      if (event.target instanceof Node && !anchor.current?.contains(event.target)) close()
    }
    document.addEventListener('keydown', key, true)
    document.addEventListener('pointerdown', outside)
    return () => {
      document.removeEventListener('keydown', key, true)
      document.removeEventListener('pointerdown', outside)
    }
  }, [open, anchor, close])
}
