// Domain dots for the SOL page (design template): one dot per ADR-027 colour token, and none
// without a domain — never a fabricated colour. Which domain a graph entity or a citation
// connector maps onto is read in domainIds.ts, so this file exports components only.
import type { DomainId } from '../../theme/tokens.constants'

export function DomainDot({
  d,
  size = 6
}: {
  d: DomainId | null
  size?: number
}): React.JSX.Element | null {
  if (!d) return null
  return (
    <span
      aria-hidden="true"
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        borderRadius: '50%',
        flex: 'none',
        background: `var(--${d})`
      }}
    />
  )
}
