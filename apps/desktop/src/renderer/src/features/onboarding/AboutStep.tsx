// Onboarding step 0 — "What are you building?" A project description plus the
// SOL-mode pick (API.md §5; ADR-016 SOL mode is a universal setting). The
// template-robot path was removed in SOLUSDEV-152: Solus only builds the graph
// from real connected sources, never from a fabricated reference project.
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Segmented } from '../../components/ui/Segmented'
import { Icons } from '../../components/ui/icons.constants'
import type { SolMode } from '../../store/settingsStore'

interface AboutStepProps {
  description: string
  onDescription: (value: string) => void
  solMode: SolMode
  onSolMode: (mode: SolMode) => void
  onContinue: () => void
}

export function AboutStep({
  description,
  onDescription,
  solMode,
  onSolMode,
  onContinue
}: AboutStepProps): React.JSX.Element {
  return (
    <div style={{ width: 660 }}>
      <h2 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: '-0.02em' }}>
        What are you building?
      </h2>
      <p style={{ color: 'var(--mut)', fontSize: 13.5, marginTop: 8, lineHeight: 1.55 }}>
        Solus uses this to name your project and tune what it looks for.
      </p>
      <ProjectDescription value={description} onChange={onDescription} />

      <DividerLabel label="HOW SHOULD SOL TALK TO YOU?" />
      <SolModeRow solMode={solMode} onSolMode={onSolMode} />

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 28 }}>
        <Button kind="primary" size="lg" onClick={onContinue}>
          Continue <Icons.arrowR size={14} />
        </Button>
      </div>
    </div>
  )
}

function ProjectDescription({
  value,
  onChange
}: {
  value: string
  onChange: (value: string) => void
}): React.JSX.Element {
  return (
    <textarea
      aria-label="Project description"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder="A 12-DOF quadruped for outdoor inspection. STM32 firmware, custom BLDC drivers, ROS 2 on a Jetson…"
      style={{
        width: '100%',
        boxSizing: 'border-box',
        height: 84,
        marginTop: 18,
        background: 'var(--sur)',
        color: 'var(--tx)',
        border: '1px solid var(--bd)',
        borderRadius: 3,
        padding: '12px 14px',
        fontSize: 13.5,
        fontFamily: 'var(--font-ui)',
        resize: 'none',
        outline: 'none',
        lineHeight: 1.5
      }}
    />
  )
}

function SolModeRow({
  solMode,
  onSolMode
}: {
  solMode: SolMode
  onSolMode: (mode: SolMode) => void
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 14 }}>
      <Segmented
        options={['Guide', 'Expert'] as const}
        value={solMode}
        onChange={onSolMode}
        ariaLabel="SOL mode"
      />
      <span style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.5 }}>
        {solMode === 'Guide'
          ? 'Explains its reasoning and teaches as it works. Switch any time in settings.'
          : 'Terse, leads with the answer. Switch any time in settings.'}
      </span>
    </div>
  )
}

function DividerLabel({ label }: { label: string }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 8, marginTop: 26, alignItems: 'center' }}>
      <Mono size={9.5}>{label}</Mono>
      <div style={{ flex: 1, height: 1, background: 'var(--bd)' }} />
    </div>
  )
}
