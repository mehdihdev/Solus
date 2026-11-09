// Onboarding step 2 — Project (server step `about`; SOLUSDEV-323,
// docs/wireflows/onboarding.md §2). The description, example sentences that
// only fill it (never a template project — SOLUSDEV-152), the worlds SOL hears
// in it, and the project name — derived from the description until the user
// types their own.
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { DOMAINS, hearDomains, heardCount } from './domainHearing'
import { deriveProjectName, projectNameFor } from './provisioning'
import { StepFooter } from './StepFooter'

export const EXAMPLE_DESCRIPTIONS = [
  {
    label: 'Quadruped',
    text: 'A 12-DOF quadruped for outdoor inspection. STM32 firmware, custom BLDC drivers, ROS 2 on a Jetson.'
  },
  {
    label: 'Robot arm',
    text: 'A 6-axis desk robot arm with a 3D-printed gripper, Onshape CAD, ESP32 servos and a teleop app.'
  },
  {
    label: 'FSAE BMS',
    text: 'An FSAE battery management board in KiCad with CAN telemetry to the pit laptop.'
  }
] as const

interface AboutStepProps {
  description: string
  onDescription: (value: string) => void
  /** The name the user typed; null = follow the description. */
  projectName: string | null
  onProjectName: (name: string | null) => void
  onNext: () => void
  onBack: () => void
}

export function AboutStep({
  description,
  onDescription,
  projectName,
  onProjectName,
  onNext,
  onBack
}: AboutStepProps): React.JSX.Element {
  const hasText = description.trim().length > 0
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        gap: 20,
        flex: 1
      }}
    >
      <div className="ob-rise ob-d2">
        <label htmlFor="ob-description">
          <Mono size={9.5}>YOUR ROBOT, IN A SENTENCE</Mono>
        </label>
        <textarea
          id="ob-description"
          aria-label="Project description"
          className="ob-textarea"
          value={description}
          onChange={(e) => onDescription(e.target.value)}
          placeholder="A 12-DOF quadruped for outdoor inspection. STM32 firmware, custom BLDC drivers, ROS 2 on a Jetson…"
          style={{
            display: 'block',
            width: '100%',
            boxSizing: 'border-box',
            height: 112,
            marginTop: 10,
            background: 'var(--sur)',
            color: 'var(--tx)',
            border: '1px solid var(--bd)',
            borderRadius: 6,
            padding: '14px 16px',
            fontSize: 15,
            lineHeight: 1.55,
            fontFamily: 'var(--font-ui)',
            resize: 'none',
            outline: 'none'
          }}
        />
      </div>
      <Examples
        onPick={(text) => {
          onDescription(text)
          onProjectName(null) // a fresh description: the name follows it again
        }}
      />
      <WorldsCard
        description={description}
        projectName={projectName}
        onProjectName={onProjectName}
      />
      <StepFooter onBack={onBack} className="ob-rise ob-d5">
        <Button kind="primary" size="lg" onClick={onNext}>
          {hasText ? 'Continue' : 'Skip — name it later'} <Icons.arrowR size={14} />
        </Button>
      </StepFooter>
    </div>
  )
}

function Examples({ onPick }: { onPick: (text: string) => void }): React.JSX.Element {
  return (
    <div
      className="ob-rise ob-d3"
      style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}
    >
      <span style={{ fontSize: 12, color: 'var(--mut)', marginRight: 4 }}>Or start from</span>
      {EXAMPLE_DESCRIPTIONS.map((ex) => (
        <button key={ex.label} type="button" className="ob-example" onClick={() => onPick(ex.text)}>
          {ex.label}
        </button>
      ))}
    </div>
  )
}

interface WorldsCardProps {
  description: string
  projectName: string | null
  onProjectName: (name: string | null) => void
}

function WorldsCard({
  description,
  projectName,
  onProjectName
}: WorldsCardProps): React.JSX.Element {
  const heard = hearDomains(description)
  const count = heardCount(heard)
  const hasText = description.trim().length > 0
  return (
    <Card pad={0} className="ob-rise ob-d4">
      <div style={{ padding: '18px 20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Mono size={9.5}>WORLDS I’M HEARING</Mono>
          <Mono size={9.5} color={count ? 'var(--acc)' : 'var(--mut)'}>
            {count ? `${count} OF 4` : 'TYPE TO START'}
          </Mono>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
          {DOMAINS.map((d) => (
            <span
              key={d.key}
              className="ob-chip"
              data-on={heard[d.key]}
              style={{ '--ob-c': d.color } as React.CSSProperties}
            >
              <span className="ob-chip-dot" />
              {d.label}
            </span>
          ))}
        </div>
        <div
          style={{
            marginTop: 16,
            paddingTop: 14,
            borderTop: '1px solid var(--bd)',
            display: 'flex',
            gap: 10,
            alignItems: 'center'
          }}
        >
          <ProjectNameField
            description={description}
            projectName={projectName}
            onProjectName={onProjectName}
            muted={!hasText && projectName === null}
          />
        </div>
      </div>
    </Card>
  )
}

const PROJECT_NAME_MAX = 80

/** The project's name: follows the description until typed in; blank falls back to it. */
function ProjectNameField({
  description,
  projectName,
  onProjectName,
  muted
}: WorldsCardProps & { muted: boolean }): React.JSX.Element {
  const derived = deriveProjectName(description)
  const edited = projectName !== null && projectNameFor(description, projectName) !== derived
  return (
    <>
      <label htmlFor="ob-project-name" style={{ flex: 'none' }}>
        <Mono size={9.5}>PROJECT NAME</Mono>
      </label>
      <input
        id="ob-project-name"
        data-testid="ob-project-name"
        aria-label="Project name"
        className="ob-name-input"
        value={projectName ?? derived}
        placeholder={derived}
        maxLength={PROJECT_NAME_MAX}
        spellCheck={false}
        onChange={(e) => onProjectName(e.target.value)}
        style={{ color: muted ? 'var(--mut)' : 'var(--tx)' }}
      />
      {edited && (
        <button type="button" className="ob-name-reset" onClick={() => onProjectName(null)}>
          Use description
        </button>
      )}
    </>
  )
}
