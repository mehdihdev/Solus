// Onboarding step 1 — "Connect your tools". Ported from step 1 in
// TestDesign/app/onboarding.jsx. Connection is a simulated animation in this
// prototype slice (no live OAuth/sync); the real flow will POST to
// /api/v1/projects/{id}/sources and stream sync jobs (API.md §2.5).
import { useEffect, useRef } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { ConnectTile } from './ConnectTile'
import { INTEGRATIONS, MIN_SOURCES_TO_BUILD, type Integration } from './integrations.constants'
import { useOnboardingStore, connectedCount, canBuildModel } from './onboardingStore'

const CONNECT_STEP_MS = 650
const COMPLETE_DELAY_MS = 350

interface ConnectStepProps {
  onBuild: () => void
}

export function ConnectStep({ onBuild }: ConnectStepProps): React.JSX.Element {
  const connections = useOnboardingStore((s) => s.connections)
  const beginConnect = useOnboardingStore((s) => s.beginConnect)
  const setConnectStep = useOnboardingStore((s) => s.setConnectStep)
  const completeConnect = useOnboardingStore((s) => s.completeConnect)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  useEffect(() => {
    const pending = timers.current
    return () => {
      pending.forEach(clearTimeout)
      pending.length = 0
    }
  }, [])

  const connect = (integ: Integration): void => {
    beginConnect(integ.id)
    integ.steps.forEach((_, i) => {
      if (i > 0) {
        timers.current.push(setTimeout(() => setConnectStep(integ.id, i), i * CONNECT_STEP_MS))
      }
    })
    timers.current.push(
      setTimeout(
        () => completeConnect(integ.id),
        integ.steps.length * CONNECT_STEP_MS + COMPLETE_DELAY_MS
      )
    )
  }

  const count = connectedCount(connections)
  const ready = canBuildModel(connections)

  return (
    <div style={{ width: 660 }}>
      <h2 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: '-0.02em' }}>
        Connect your tools
      </h2>
      <p style={{ color: 'var(--mut)', fontSize: 13.5, marginTop: 8, lineHeight: 1.55 }}>
        Each source becomes a domain in your context model. Connect at least two — cross-domain
        checks need something to cross.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 24 }}>
        {INTEGRATIONS.map((integ) => (
          <ConnectTile
            key={integ.id}
            integration={integ}
            state={connections[integ.id]}
            onConnect={() => connect(integ)}
          />
        ))}
      </div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: 28
        }}
      >
        <Mono size={10} color={ready ? 'var(--ok)' : 'var(--mut)'}>
          {count} OF {INTEGRATIONS.length} CONNECTED{' '}
          {ready ? '— READY' : `(NEED ${MIN_SOURCES_TO_BUILD}+)`}
        </Mono>
        <Button kind="primary" size="lg" disabled={!ready} onClick={onBuild}>
          Build context model <Icons.arrowR size={14} />
        </Button>
      </div>
    </div>
  )
}
