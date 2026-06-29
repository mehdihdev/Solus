// Solus wordmark (orb + SOLUS), ported from SolusWordmark in TestDesign/app/auth.jsx.
import { SolOrb } from './SolOrb'

interface WordmarkProps {
  size?: number
  onClick?: () => void
}

export function Wordmark({ size = 16, onClick }: WordmarkProps): React.JSX.Element {
  return (
    <div
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        cursor: onClick ? 'pointer' : 'default'
      }}
    >
      <SolOrb size={size + 2} />
      <span style={{ fontWeight: 700, fontSize: size, letterSpacing: '0.12em' }}>SOLUS</span>
    </div>
  )
}
