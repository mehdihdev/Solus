// Onboarding step 3 — Voice (SOLUSDEV-323, docs/wireflows/onboarding.md §3):
// the SOL tone (ADR-016 `sol_mode`) shown rather than described — one fixed
// question answered in the chosen voice. Static, Solus-authored copy.
import { useRef } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import type { SolMode } from '../../store/settingsStore'
import { StepFooter } from './StepFooter'

const CHOICES: ReadonlyArray<{ mode: SolMode; tag: string; body: string }> = [
  {
    mode: 'Guide',
    tag: 'NEW TO A DOMAIN',
    body: 'Explains its reasoning, teaches the concept, links the fundamentals.'
  },
  { mode: 'Expert', tag: 'YOU KNOW THE DRILL', body: 'Terse. Leads with the answer and the fix.' }
]

interface VoiceStepProps {
  solMode: SolMode
  onSolMode: (mode: SolMode) => void
  onNext: () => void
  onBack: () => void
}

const NEXT_KEYS = new Set(['ArrowRight', 'ArrowDown'])
const PREV_KEYS = new Set(['ArrowLeft', 'ArrowUp'])

/** Arrow keys move the choice and focus together (ARIA radio group, roving tabindex). */
function useRovingRadios(
  solMode: SolMode,
  onSolMode: (mode: SolMode) => void
): {
  refs: React.MutableRefObject<(HTMLButtonElement | null)[]>
  onKeyDown: (e: React.KeyboardEvent) => void
} {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const onKeyDown = (e: React.KeyboardEvent): void => {
    const step = NEXT_KEYS.has(e.key) ? 1 : PREV_KEYS.has(e.key) ? -1 : 0
    if (step === 0) return
    e.preventDefault()
    const current = CHOICES.findIndex((c) => c.mode === solMode)
    const next = (current + step + CHOICES.length) % CHOICES.length
    onSolMode(CHOICES[next].mode)
    refs.current[next]?.focus()
  }
  return { refs, onKeyDown }
}

export function VoiceStep({
  solMode,
  onSolMode,
  onNext,
  onBack
}: VoiceStepProps): React.JSX.Element {
  const radios = useRovingRadios(solMode, onSolMode)
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        gap: 18,
        flex: 1
      }}
    >
      <div
        role="radiogroup"
        aria-label="SOL mode"
        onKeyDown={radios.onKeyDown}
        className="ob-rise ob-d2"
        style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 14 }}
      >
        {CHOICES.map((c, i) => (
          <button
            key={c.mode}
            ref={(el) => {
              radios.refs.current[i] = el
            }}
            type="button"
            role="radio"
            aria-checked={solMode === c.mode}
            tabIndex={solMode === c.mode ? 0 : -1}
            className="ob-choice"
            onClick={() => onSolMode(c.mode)}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 15, fontWeight: 600 }}>{c.mode}</span>
              <Mono size={9}>{c.tag}</Mono>
            </div>
            <div style={{ fontSize: 13, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 }}>
              {c.body}
            </div>
          </button>
        ))}
      </div>
      <Card pad={0} className="ob-rise ob-d3">
        <div style={{ padding: 20, minHeight: 236, boxSizing: 'border-box' }}>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <span
              style={{
                background: 'var(--sur2)',
                border: '1px solid var(--bd)',
                borderRadius: '10px 10px 2px 10px',
                padding: '8px 12px',
                fontSize: 13
              }}
            >
              Why does my I²C bus hang on boot?
            </span>
          </div>
          <div style={{ display: 'flex', gap: 12, marginTop: 16, alignItems: 'flex-start' }}>
            <span
              className="ob-dot"
              style={{ width: 22, height: 22, marginTop: 2 }}
              aria-hidden="true"
            />
            {solMode === 'Guide' ? <GuideAnswer key="guide" /> : <ExpertAnswer key="expert" />}
          </div>
        </div>
      </Card>
      <StepFooter onBack={onBack} className="ob-rise ob-d4">
        <Button kind="primary" size="lg" onClick={onNext}>
          Use {solMode} <Icons.arrowR size={14} />
        </Button>
      </StepFooter>
    </div>
  )
}

const ANSWER = { fontSize: 13.5, lineHeight: 1.65, color: 'var(--tx)' } as const

function GuideAnswer(): React.JSX.Element {
  return (
    <div className="ob-rise" style={ANSWER}>
      <div>
        Two chips on your bus answer to the same address, <b>0x68</b> — the IMU and the real-time
        clock. When both reply at once, the bus locks up.
      </div>
      <div
        style={{
          marginTop: 10,
          padding: '10px 12px',
          borderRadius: 4,
          background: 'var(--sur2)',
          border: '1px solid var(--bd)',
          color: 'var(--mut)',
          fontSize: 12.5
        }}
      >
        <Mono size={9} color="var(--ee)">
          CONCEPT · I²C ADDRESSES
        </Mono>
        <div style={{ marginTop: 4 }}>
          Every device on an I²C bus has a 7-bit address, like a house number. Two houses can’t
          share one.
        </div>
      </div>
      <div style={{ marginTop: 10 }}>
        The fix: pull the IMU’s AD0 pin high to move it to 0x69. Want me to show you where that pin
        is in KiCad?
      </div>
    </div>
  )
}

function ExpertAnswer(): React.JSX.Element {
  return (
    <div className="ob-rise" style={ANSWER}>
      <div>
        Address collision at <b>0x68</b>: IMU vs RTC.
      </div>
      <div
        style={{ marginTop: 8, fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--mut)' }}
      >
        → tie IMU AD0 to 3V3 (0x69)
        <br />→ update IMU_ADDR in imu.cpp
      </div>
    </div>
  )
}
