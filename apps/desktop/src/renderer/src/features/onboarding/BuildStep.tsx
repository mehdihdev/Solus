// Onboarding step 2 — "Building your context model". Ported from step 2 in
// TestDesign/app/onboarding.jsx. The build log is a simulated animation; the
// real flow runs sync + checker jobs and streams progress (API.md §2.5/§2.16).
import { useEffect } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { useOnboardingStore } from './onboardingStore'
import { BUILD_LOG_LINES } from './integrations.constants'

const FIRST_LINE_MS = 500
const PER_LINE_MS = 750
const FINISH_PAD_MS = 400

interface BuildStepProps {
  onComplete: () => void
}

export function BuildStep({ onComplete }: BuildStepProps): React.JSX.Element {
  const buildLog = useOnboardingStore((s) => s.buildLog)
  const buildDone = useOnboardingStore((s) => s.buildDone)
  const appendBuildLine = useOnboardingStore((s) => s.appendBuildLine)
  const finishBuild = useOnboardingStore((s) => s.finishBuild)
  const resetBuild = useOnboardingStore((s) => s.resetBuild)

  // Every mount restarts the animation from a clean log — no once-only ref:
  // under StrictMode the first mount's timers are cleared by cleanup, so the
  // second mount MUST reschedule or the build never finishes. A build that
  // already completed (resume-to-done) is left as-is.
  useEffect(() => {
    if (useOnboardingStore.getState().buildDone) return
    resetBuild()
    const timers: ReturnType<typeof setTimeout>[] = []
    BUILD_LOG_LINES.forEach((line, i) => {
      timers.push(setTimeout(() => appendBuildLine(line), FIRST_LINE_MS + i * PER_LINE_MS))
    })
    timers.push(
      setTimeout(finishBuild, FIRST_LINE_MS + BUILD_LOG_LINES.length * PER_LINE_MS + FINISH_PAD_MS)
    )
    return () => timers.forEach(clearTimeout)
  }, [appendBuildLine, finishBuild, resetBuild])

  return (
    <div style={{ width: 560 }}>
      <h2 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: '-0.02em' }}>
        {buildDone ? 'Context model ready' : 'Building your context model'}
      </h2>
      <p style={{ color: 'var(--mut)', fontSize: 13.5, marginTop: 8 }}>
        {buildDone
          ? '247 nodes · 31 cross-domain links · 2 issues already flagged'
          : 'Linking everything your robot is made of…'}
      </p>
      <Card pad={0} style={{ marginTop: 24, fontFamily: 'var(--font-mono)' }}>
        {buildLog.map(([left, right], i) => (
          <div
            key={`${left}-${i}`}
            className="ob-logline"
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              padding: '9px 16px',
              borderBottom: '1px solid var(--bd)',
              fontSize: 11
            }}
          >
            <span
              style={{ color: 'var(--tx)', display: 'inline-flex', alignItems: 'center', gap: 10 }}
            >
              <span style={{ color: 'var(--ok)' }}>
                <Icons.check size={12} />
              </span>
              {left}
            </span>
            <span style={{ color: 'var(--mut)' }}>{right}</span>
          </div>
        ))}
        {!buildDone && (
          <div
            style={{
              display: 'flex',
              gap: 10,
              padding: '9px 16px',
              fontSize: 11,
              color: 'var(--acc)',
              alignItems: 'center'
            }}
          >
            <Spinner size={11} /> working…
          </div>
        )}
      </Card>
      {buildDone && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 24 }}>
          <Button kind="primary" size="lg" onClick={onComplete}>
            Open workspace <Icons.arrowR size={14} />
          </Button>
        </div>
      )}
    </div>
  )
}
