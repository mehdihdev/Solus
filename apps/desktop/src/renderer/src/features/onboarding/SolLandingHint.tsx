// SOLUSDEV-323 Land (docs/wireflows/onboarding.md §7): the one-time SOL pill on
// the workspace right after onboarding — "double-tap ctrl from any app".
// Dismissable; hides itself after LANDING_HINT_MS. Shown once per completion.
import { useEffect } from 'react'
import { Button } from '../../components/ui/Button'
import { useOnboardingStore } from './onboardingStore'
import './onboarding.css'

export const LANDING_HINT_MS = 9000

export function SolLandingHint(): React.JSX.Element | null {
  const show = useOnboardingStore((s) => s.landingHint)
  const setLandingHint = useOnboardingStore((s) => s.setLandingHint)
  useEffect(() => {
    if (!show) return
    const timer = setTimeout(() => setLandingHint(false), LANDING_HINT_MS)
    return () => clearTimeout(timer)
  }, [show, setLandingHint])
  if (!show) return null
  return (
    <div role="status" className="ob-pill ob-root">
      <span className="ob-dot" style={{ width: 26, height: 26 }} aria-hidden="true" />
      <span style={{ fontSize: 12.5, color: 'var(--mut)', paddingRight: 6 }}>
        I’m here whenever — double-tap ctrl from any app.
      </span>
      <Button kind="bare" size="sm" onClick={() => setLandingHint(false)}>
        Dismiss
      </Button>
    </div>
  )
}
