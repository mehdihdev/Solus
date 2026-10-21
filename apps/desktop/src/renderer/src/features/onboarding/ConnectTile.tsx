// Connect tile (SOLUSDEV-165): a LAUNCHER for the connect wizard. The tile
// shows the integration's identity and live status (busy label, real result,
// honest error) and opens the wizard on click — every in-flow input (grant
// choice, picker, details form, file pick) lives in ConnectWizardModal now.
// No copy here is ever fabricated, so a new connector needs no change.
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import type { Integration } from './integrations.constants'
import { integrationLogo, logoClass } from './integrationLogos'
import type { ConnectionState } from './onboardingStore'

interface ConnectTileProps {
  integration: Integration
  state?: ConnectionState
  unavailableReason?: string | null
  /** Open the connect wizard for this integration. */
  onOpen: () => void
}

function TileIndicator({ state }: { state?: ConnectionState }): React.JSX.Element {
  if (!state)
    return <span style={{ color: 'var(--acc)', fontSize: 12, fontWeight: 500 }}>Connect</span>
  if (state.phase === 'busy') return <Spinner />
  if (state.phase === 'error')
    return <span style={{ color: 'var(--err)', fontSize: 12, fontWeight: 500 }}>Retry</span>
  return (
    <span style={{ color: 'var(--ok)' }}>
      <Icons.check size={15} />
    </span>
  )
}

const MONO = { fontFamily: 'var(--font-mono)', fontSize: 10.5 } as const

function TileFooter({ state }: { state?: ConnectionState }): React.JSX.Element {
  if (!state) return <span style={{ fontSize: 11, color: 'var(--mut)' }}>Not connected</span>
  if (state.phase === 'busy') {
    return <span style={{ ...MONO, color: 'var(--acc)' }}>{state.label ?? 'Connecting…'}</span>
  }
  if (state.phase === 'error') {
    return <span style={{ ...MONO, color: 'var(--err)' }}>{state.error}</span>
  }
  return <span style={{ ...MONO, color: 'var(--ok)' }}>{state.result ?? 'Connected'}</span>
}

function borderFor(state?: ConnectionState): string {
  if (state?.phase === 'done') return 'color-mix(in srgb, var(--ok) 45%, var(--bd))'
  if (state?.phase === 'error') return 'color-mix(in srgb, var(--err) 45%, var(--bd))'
  if (state?.phase === 'busy') return 'var(--acc)'
  return 'var(--bd)'
}

function TileMark({ integration }: { integration: Integration }): React.JSX.Element {
  const logo = integrationLogo(integration.id)
  return (
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
        flexShrink: 0,
        overflow: 'hidden'
      }}
    >
      {logo ? (
        <img
          src={logo}
          alt=""
          className={logoClass(integration.id)}
          style={{ width: 26, height: 26, objectFit: 'contain' }}
        />
      ) : (
        integration.mark
      )}
    </span>
  )
}

export function ConnectTile({
  integration,
  state,
  onOpen,
  unavailableReason
}: ConnectTileProps): React.JSX.Element {
  return (
    <Card
      pad={0}
      onClick={unavailableReason ? undefined : onOpen}
      aria-disabled={unavailableReason ? true : undefined}
      style={{
        cursor: unavailableReason ? 'default' : 'pointer',
        overflow: 'hidden',
        borderColor: borderFor(unavailableReason ? undefined : state),
        transition: 'border-color 0.2s'
      }}
    >
      <div style={{ padding: '16px 16px 14px', display: 'flex', gap: 12, alignItems: 'center' }}>
        <TileMark integration={integration} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{integration.name}</div>
          <div style={{ fontSize: 11, color: 'var(--mut)' }}>{integration.kind}</div>
        </div>
        {unavailableReason ? (
          <span style={{ color: 'var(--mut)', fontSize: 12 }}>Unavailable</span>
        ) : (
          <TileIndicator state={state} />
        )}
      </div>
      <div
        style={{
          borderTop: '1px solid var(--bd)',
          padding: '9px 16px',
          minHeight: 16,
          background: 'var(--bg)'
        }}
      >
        {unavailableReason ? (
          <span style={{ color: 'var(--mut)', fontSize: 11 }}>{unavailableReason}</span>
        ) : (
          <TileFooter state={state} />
        )}
      </div>
    </Card>
  )
}
