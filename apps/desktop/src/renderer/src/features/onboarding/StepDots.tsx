// Step progress dots, ported from ObStepDots in TestDesign/app/onboarding.jsx.
import { Fragment } from 'react'
import { Mono } from '../../components/ui/Mono'

const STEPS = ['About', 'Connect', 'Build'] as const

export function StepDots({ step }: { step: number }): React.JSX.Element {
  return (
    <div
      style={{ display: 'flex', gap: 8, alignItems: 'center' }}
      aria-label={`Step ${step + 1} of 3`}
    >
      {STEPS.map((label, i) => {
        const reached = i <= step
        return (
          <Fragment key={label}>
            {i > 0 && (
              <div
                style={{ width: 26, height: 1, background: reached ? 'var(--acc)' : 'var(--bd)' }}
              />
            )}
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: 99,
                  background: reached ? 'var(--acc)' : 'var(--bd)'
                }}
              />
              <Mono size={9.5} color={reached ? 'var(--tx)' : 'var(--mut)'}>
                {label}
              </Mono>
            </span>
          </Fragment>
        )
      })}
    </div>
  )
}
