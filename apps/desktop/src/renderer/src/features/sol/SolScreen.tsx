// SOL screen. Chat wiring to the real SOL backend lands with SOLUSDEV-132/134;
// SOLUSDEV-152 removed the scripted prototype conversation, fake think-delays,
// the fabricated grounding footer, and the fake apply-&-flash flow. Until the
// backend is wired this is an honest not-connected state that keeps SOL's
// visual identity (the orb) and the universal Guide/Expert mode setting
// (ADR-016).
import { Mono } from '../../components/ui/Mono'
import { Segmented } from '../../components/ui/Segmented'
import { SolOrb } from '../../components/ui/SolOrb'
import { useSettingsStore, type SolMode } from '../../store/settingsStore'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'

export function SolScreen(): React.JSX.Element {
  const solMode = useSettingsStore((s) => s.solMode)
  const setSolMode = useSettingsStore((s) => s.setSolMode)

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0 }}>
      <SolHeader solMode={solMode} setSolMode={setSolMode} />
      <ScreenEmptyState
        icon={<SolOrb size={44} />}
        title="SOL isn't wired to this workspace yet"
        body={
          <>
            Once connected, SOL answers questions about your robot with evidence from the graph —
            tracing causes across firmware, electronics, CAD, and runtime — in the mode you choose
            above. Chat arrives in an upcoming update.
          </>
        }
      />
    </div>
  )
}

function SolHeader({
  solMode,
  setSolMode
}: {
  solMode: SolMode
  setSolMode: (m: SolMode) => void
}): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '16px 24px 10px',
        maxWidth: 800,
        width: '100%',
        margin: '0 auto',
        boxSizing: 'border-box'
      }}
    >
      <SolOrb size={56} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 16, fontWeight: 600 }}>SOL</div>
        <Mono size={9.5} color="var(--mut)">
          NOT CONNECTED
        </Mono>
      </div>
      <div style={{ textAlign: 'right' }}>
        <Segmented options={['Guide', 'Expert']} value={solMode} onChange={setSolMode} />
        <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 5 }}>
          {solMode === 'Guide' ? 'explains and teaches' : 'terse, direct'}
        </div>
      </div>
    </div>
  )
}
