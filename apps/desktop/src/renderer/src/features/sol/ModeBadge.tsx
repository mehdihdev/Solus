// SOLUSDEV-252 S3: the action-mode badge — Guide | Build (wireflow §B). One
// click toggles, the same as Ctrl+Space; the label reflects main's setting so
// every surface (page composer, window header, tray) reads the same value.
import type { SolActionMode } from './solApi'
import { MODE_LABEL, oppositeMode } from './solWindowStore'

interface ModeBadgeProps {
  mode: SolActionMode
  onChange: (mode: SolActionMode) => void
}

export function ModeBadge({ mode, onChange }: ModeBadgeProps): React.JSX.Element {
  return (
    <button
      type="button"
      className="sol-mode-badge"
      aria-label="SOL action mode"
      title={`${MODE_LABEL[mode]} — click to switch (Ctrl+Space)`}
      onClick={() => onChange(oppositeMode(mode))}
    >
      {MODE_LABEL[mode]}
    </button>
  )
}
