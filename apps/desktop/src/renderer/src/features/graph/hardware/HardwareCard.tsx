// One entry card in the Add › Hardware grid: title, one-line kind, status
// footer. Mirrors ConnectTile's card-in-a-grid shape, compact for the popover.
// The Card IS the button for assistive tech (role/tabIndex pass through).
import { useId } from 'react'
import { Card } from '../../../components/ui/Card'
import type { HardwareCard as HardwareCardData } from './hardware.constants'

interface HardwareCardProps {
  card: HardwareCardData
  disabled: boolean
  onOpen: () => void
}

export function HardwareCard({ card, disabled, onOpen }: HardwareCardProps): React.JSX.Element {
  const id = useId()
  const open = disabled ? undefined : onOpen
  return (
    <Card
      pad={0}
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-status`}
      aria-disabled={disabled || undefined}
      onClick={open}
      onKeyDown={(event) => {
        if (open && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault()
          open()
        }
      }}
      style={{
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.55 : 1,
        overflow: 'hidden'
      }}
    >
      <div style={{ padding: '10px 12px 8px', minWidth: 0 }}>
        <div id={`${id}-title`} style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--tx)' }}>
          {card.title}
        </div>
        <div
          style={{
            fontSize: 11,
            color: 'var(--mut)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis'
          }}
        >
          {card.kind}
        </div>
      </div>
      <div
        id={`${id}-status`}
        style={{
          borderTop: '1px solid var(--bd)',
          padding: '6px 12px',
          background: 'var(--bg)',
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--mut)'
        }}
      >
        {card.status}
      </div>
    </Card>
  )
}
