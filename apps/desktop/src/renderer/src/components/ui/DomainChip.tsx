// Domain pill (Software/Electrical/Mechanical/Runtime), ported from
// DomainChip in TestDesign/app/util.jsx. Colors come from the domain tokens.
import { SOLUS_DOMAINS, dcol, type DomainId } from '../../theme/tokens.constants'

interface DomainChipProps {
  d: DomainId
  on?: boolean
  onClick?: () => void
  small?: boolean
}

export function DomainChip({ d, on = true, onClick, small }: DomainChipProps): React.JSX.Element {
  const c = dcol(d)
  const domainVar = `var(${SOLUS_DOMAINS[d].varName})`
  return (
    <span
      onClick={onClick}
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: small ? 9 : 10,
        letterSpacing: '0.05em',
        padding: small ? '3px 8px' : '5px 10px',
        borderRadius: 99,
        cursor: onClick ? 'pointer' : 'default',
        color: on ? c : 'var(--mut)',
        background: on ? `color-mix(in srgb, ${domainVar} 9%, transparent)` : 'transparent',
        border: `1px solid ${on ? `color-mix(in srgb, ${domainVar} 30%, transparent)` : 'var(--bd)'}`,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        userSelect: 'none',
        whiteSpace: 'nowrap'
      }}
    >
      <span
        style={{
          width: 5,
          height: 5,
          borderRadius: 99,
          background: on ? c : 'var(--mut)',
          display: 'inline-block'
        }}
      />
      {SOLUS_DOMAINS[d].label}
    </span>
  )
}
