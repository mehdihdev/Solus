// Connect tile, ported from ConnectTile in TestDesign/app/onboarding.jsx.
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import type { Integration } from './integrations.constants'
import type { ConnectionState } from './onboardingStore'

interface ConnectTileProps {
  integration: Integration
  state?: ConnectionState
  onConnect: () => void
}

function TileIndicator({ state }: { state?: ConnectionState }): React.JSX.Element {
  if (!state)
    return <span style={{ color: 'var(--acc)', fontSize: 12, fontWeight: 500 }}>Connect</span>
  if (state.phase === 'busy') return <Spinner />
  return (
    <span style={{ color: 'var(--ok)' }}>
      <Icons.check size={15} />
    </span>
  )
}

function TileFooter({
  integration,
  state
}: {
  integration: Integration
  state?: ConnectionState
}): React.JSX.Element {
  const mono = { fontFamily: 'var(--font-mono)', fontSize: 10.5 } as const
  if (!state) return <span style={{ fontSize: 11, color: 'var(--mut)' }}>Not connected</span>
  if (state.phase === 'busy') {
    return <span style={{ ...mono, color: 'var(--acc)' }}>{integration.steps[state.stepIdx]}</span>
  }
  return <span style={{ ...mono, color: 'var(--ok)' }}>{integration.result}</span>
}

function borderFor(state?: ConnectionState): string {
  if (state?.phase === 'done') return 'color-mix(in srgb, var(--ok) 45%, var(--bd))'
  if (state?.phase === 'busy') return 'var(--acc)'
  return 'var(--bd)'
}

export function ConnectTile({
  integration,
  state,
  onConnect
}: ConnectTileProps): React.JSX.Element {
  const idle = !state
  return (
    <Card
      pad={0}
      onClick={idle ? onConnect : undefined}
      style={{
        cursor: idle ? 'pointer' : 'default',
        overflow: 'hidden',
        borderColor: borderFor(state),
        transition: 'border-color 0.2s'
      }}
    >
      <div style={{ padding: '16px 16px 14px', display: 'flex', gap: 12, alignItems: 'center' }}>
        <span
          style={{
            width: 38,
            height: 38,
            borderRadius: 3,
            background: 'var(--sur2)',
            border: '1px solid var(--bd)',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            fontWeight: 500,
            color: 'var(--tx)',
            flexShrink: 0
          }}
        >
          {integration.mark}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{integration.name}</div>
          <div style={{ fontSize: 11, color: 'var(--mut)' }}>{integration.kind}</div>
        </div>
        <TileIndicator state={state} />
      </div>
      <div
        style={{
          borderTop: '1px solid var(--bd)',
          padding: '9px 16px',
          minHeight: 16,
          background: 'var(--bg)'
        }}
      >
        <TileFooter integration={integration} state={state} />
      </div>
    </Card>
  )
}
