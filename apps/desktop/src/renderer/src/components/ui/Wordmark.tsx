// Solus wordmark (logo + SOLUS). SOLUSDEV-233: the brand mark is the bundled
// logo; SOL itself lives on the SOL page and the SOL window (SOLUSDEV-252).
import { SolusLogo } from './SolusLogo'

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
      <SolusLogo size={size + 6} />
      <span style={{ fontWeight: 700, fontSize: size, letterSpacing: '0.12em' }}>SOLUS</span>
    </div>
  )
}
