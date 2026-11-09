// The onboarding progress rail (SOLUSDEV-323, docs/wireflows/onboarding.md
// §Layout): six segments — earlier steps full, the current one half filled —
// with mono labels. Kept as `StepDots` (the design-sync export name).
import { Mono } from '../../components/ui/Mono'
import { ONBOARDING_STEP_LABELS } from './onboardingStore'

const SEGMENT_WIDTH = 84

function fillFor(index: number, step: number): number {
  if (index < step) return 1
  return index === step ? 0.5 : 0
}

export function StepDots({ step }: { step: number }): React.JSX.Element {
  return (
    <ol
      aria-label={`Step ${step + 1} of ${ONBOARDING_STEP_LABELS.length}`}
      style={{
        display: 'flex',
        gap: 10,
        alignItems: 'flex-start',
        listStyle: 'none',
        margin: 0,
        padding: 0
      }}
    >
      {ONBOARDING_STEP_LABELS.map((label, i) => (
        <li
          key={label}
          aria-current={i === step ? 'step' : undefined}
          style={{ width: SEGMENT_WIDTH, display: 'flex', flexDirection: 'column', gap: 8 }}
        >
          <div className="ob-seg">
            <div className="ob-seg-fill" style={{ transform: `scaleX(${fillFor(i, step)})` }} />
          </div>
          <Mono size={9.5} color={i <= step ? 'var(--tx)' : 'var(--mut)'}>
            {label}
          </Mono>
        </li>
      ))}
    </ol>
  )
}
