// Onboarding step 0 — "What are you building?" Ported from step 0 in
// TestDesign/app/onboarding.jsx, with a SOL-mode pick folded in (API.md §5
// "pick SOL mode"; ADR-016 SOL mode is a universal setting).
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Card } from '../../components/ui/Card'
import { Segmented } from '../../components/ui/Segmented'
import { Icons } from '../../components/ui/icons.constants'
import { TEMPLATE_ROBOTS } from './integrations.constants'
import type { StartingPoint } from './onboardingStore'
import type { SolMode } from '../../store/settingsStore'

interface AboutStepProps {
  description: string
  onDescription: (value: string) => void
  path: StartingPoint
  onPath: (path: StartingPoint) => void
  templateId: string | null
  onTemplate: (id: string) => void
  solMode: SolMode
  onSolMode: (mode: SolMode) => void
  onContinue: () => void
}

const PATH_CARDS: { id: StartingPoint; title: string; body: string }[] = [
  {
    id: 'connect',
    title: 'Connect my existing tools',
    body: 'GitHub, KiCad, Onshape, ROS 2 — Solus builds the graph from your real sources.'
  },
  {
    id: 'template',
    title: 'Start from a template robot',
    body: 'No project yet? Explore with a fully-wired reference robot and simulated bench.'
  }
]

export function AboutStep({
  description,
  onDescription,
  path,
  onPath,
  templateId,
  onTemplate,
  solMode,
  onSolMode,
  onContinue
}: AboutStepProps): React.JSX.Element {
  const isTemplate = path === 'template'
  const continueDisabled = isTemplate && !templateId

  return (
    <div style={{ width: 660 }}>
      <h2 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: '-0.02em' }}>
        What are you building?
      </h2>
      <p style={{ color: 'var(--mut)', fontSize: 13.5, marginTop: 8, lineHeight: 1.55 }}>
        Solus uses this to name your project and tune what it looks for.
      </p>
      <ProjectDescription value={description} onChange={onDescription} />

      <DividerLabel label="STARTING POINT" />
      <StartingPointCards path={path} onPath={onPath} />

      {isTemplate && <TemplatePicker templateId={templateId} onTemplate={onTemplate} />}

      <DividerLabel label="HOW SHOULD SOL TALK TO YOU?" />
      <SolModeRow solMode={solMode} onSolMode={onSolMode} />

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 28 }}>
        <Button kind="primary" size="lg" disabled={continueDisabled} onClick={onContinue}>
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

function StartingPointCards({
  path,
  onPath
}: {
  path: StartingPoint
  onPath: (path: StartingPoint) => void
}): React.JSX.Element {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 14 }}>
      {PATH_CARDS.map((c) => (
        <Card
          key={c.id}
          pad={16}
          onClick={() => onPath(c.id)}
          style={{ cursor: 'pointer', borderColor: path === c.id ? 'var(--acc)' : 'var(--bd)' }}
        >
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{c.title}</div>
          <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 4, lineHeight: 1.5 }}>
            {c.body}
          </div>
        </Card>
      ))}
    </div>
  )
}

function TemplatePicker({
  templateId,
  onTemplate
}: {
  templateId: string | null
  onTemplate: (id: string) => void
}): React.JSX.Element {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginTop: 14 }}>
      {TEMPLATE_ROBOTS.map((t) => (
        <Card
          key={t.id}
          pad={14}
          onClick={() => onTemplate(t.id)}
          style={{
            cursor: 'pointer',
            textAlign: 'center',
            borderColor: templateId === t.id ? 'var(--acc)' : 'var(--bd)'
          }}
        >
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 17,
              color: templateId === t.id ? 'var(--acc)' : 'var(--mut)'
            }}
          >
            {t.body}
          </div>
          <div style={{ fontSize: 12.5, fontWeight: 600, marginTop: 6 }}>{t.name}</div>
          <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 3 }}>{t.sub}</div>
        </Card>
      ))}
    </div>
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
