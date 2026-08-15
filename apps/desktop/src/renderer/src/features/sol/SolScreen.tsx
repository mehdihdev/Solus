// SOL screen (SOLX-02 / SOLUSDEV-201): the full-page chat surface. The
// SOLUSDEV-152 honest not-connected state is retired — the SOLUSDEV-135
// backend is live, and the screen reuses OrbChat (the same surface as the
// persistent orb's panel). Keeps SOL's visual identity and the universal
// Guide/Expert mode setting (ADR-016) in the header.
import { Mono } from '../../components/ui/Mono'
import { Segmented } from '../../components/ui/Segmented'
import { SolOrb } from '../../components/ui/SolOrb'
import { useSettingsStore, type SolMode } from '../../store/settingsStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { OrbChat } from './OrbChat'
import { selectOrbPulse, useOrbStore } from './orbStore'

export function SolScreen(): React.JSX.Element {
  const solMode = useSettingsStore((s) => s.solMode)
  const setSolMode = useSettingsStore((s) => s.setSolMode)
  const project = useWorkspaceStore((s) => s.project)

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0 }}>
      <SolHeader solMode={solMode} setSolMode={setSolMode} projectName={project?.name ?? null} />
      <OrbChat projectId={project?.id ?? null} layout="page" />
    </div>
  )
}

function SolHeader({
  solMode,
  setSolMode,
  projectName
}: {
  solMode: SolMode
  setSolMode: (m: SolMode) => void
  projectName: string | null
}): React.JSX.Element {
  const pulse = useOrbStore(selectOrbPulse)
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
      <SolOrb size={56} pulse={pulse} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 16, fontWeight: 600 }}>SOL</div>
        <Mono size={9.5} color="var(--mut)">
          {projectName ?? 'NO PROJECT'}
        </Mono>
      </div>
      <div style={{ textAlign: 'right' }}>
        <Segmented
          options={['Guide', 'Expert']}
          value={solMode}
          onChange={setSolMode}
          ariaLabel="SOL mode"
        />
        <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 5 }}>
          {solMode === 'Guide' ? 'explains and teaches' : 'terse, direct'}
        </div>
      </div>
    </div>
  )
}
