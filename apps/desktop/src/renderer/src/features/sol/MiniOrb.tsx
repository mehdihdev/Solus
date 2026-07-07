// Floating corner orb, ported from MiniOrb in TestDesign/app/sol.jsx
// ('corner' mode; the prototype's follow-mouse mode is intentionally omitted).
import { SolOrb } from '../../components/ui/SolOrb'

interface MiniOrbProps {
  hidden: boolean
  onClick: () => void
}

export function MiniOrb({ hidden, onClick }: MiniOrbProps): React.JSX.Element | null {
  if (hidden) return null
  return (
    <div style={{ position: 'fixed', right: 18, bottom: 18, zIndex: 60 }} title="Ask SOL">
      <button
        aria-label="Ask SOL"
        onClick={onClick}
        style={{
          background: 'transparent',
          border: 'none',
          padding: 0,
          cursor: 'pointer',
          display: 'block'
        }}
      >
        <SolOrb size={44} />
      </button>
    </div>
  )
}
