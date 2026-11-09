// The Connect step's ring (SOLUSDEV-323, docs/wireflows/onboarding.md §5): the
// live catalog on an ellipse round a small orb. A connected tool glows in its
// domain colour and a wire draws in from the orb. Past RING_MAX, the rest sit
// in the ordinary grid below. Tiles only launch the real connect flows.
import { useEffect, useRef, useState } from 'react'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { ConnectTile, TileMark } from './ConnectTile'
import { domainForIntegration, DOMAINS } from './domainHearing'
import type { CatalogEntry } from './integrationCatalog'
import { OnboardingOrb } from './OnboardingOrb'
import { RING_MAX, RING_TILE_WIDTH, ringRadiusFor, ringSlots } from './onboardingLayout'
import type { ConnectionState } from './onboardingStore'
import type { CatalogConnect } from './useCatalogConnect'

const RING_HEIGHT = 440

function colorFor(id: string): string {
  const domain = domainForIntegration(id)
  return DOMAINS.find((d) => d.key === domain)?.color ?? 'var(--acc)'
}

function statusFor(entry: CatalogEntry, state: ConnectionState | undefined): string {
  if (!state) return entry.kind
  if (state.phase === 'busy') return state.label ?? 'Connecting…'
  if (state.phase === 'error') return state.error
  return state.result ?? 'Connected'
}

interface ConnectRingProps {
  connect: CatalogConnect
  suggested: ReadonlySet<string>
}

/** The element's content width, live (null until measured / without ResizeObserver). */
function useWidth(): [React.RefObject<HTMLDivElement | null>, number | null] {
  const ref = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState<number | null>(null)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return [ref, width]
}

export function ConnectRing({ connect, suggested }: ConnectRingProps): React.JSX.Element {
  const [measureRef, width] = useWidth()
  const rx = ringRadiusFor(width)
  // Too narrow for any ring: every tool goes in the grid, still fully reachable.
  const ring = rx === null ? [] : connect.catalog.slice(0, RING_MAX)
  const rest = rx === null ? connect.catalog : connect.catalog.slice(RING_MAX)
  const slots = ringSlots(ring.length, { rx: rx ?? undefined })
  const anyConnected = ring.some((e) => connect.connections[e.id]?.phase === 'done')
  return (
    <div ref={measureRef} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {ring.length > 0 && (
        <div style={{ position: 'relative', height: RING_HEIGHT, flex: 'none' }}>
          {ring.map((entry, i) =>
            connect.connections[entry.id]?.phase === 'done' ? (
              <div
                key={`wire-${entry.id}`}
                data-testid="ob-wire"
                className="ob-wire"
                style={
                  {
                    width: slots[i].wireLength,
                    '--ob-a': `${slots[i].wireAngle}deg`,
                    '--ob-c': colorFor(entry.id)
                  } as React.CSSProperties
                }
              />
            ) : null
          )}
          <div
            style={{
              position: 'absolute',
              left: '50%',
              top: '50%',
              transform: 'translate(-50%, -50%)'
            }}
          >
            <OnboardingOrb state={anyConnected ? 'listening' : 'idle'} size="hub" />
          </div>
          {ring.map((entry, i) => (
            <div
              key={entry.id}
              style={{
                position: 'absolute',
                left: `calc(50% + ${slots[i].x}px)`,
                top: `calc(50% + ${slots[i].y}px)`,
                transform: 'translate(-50%, -50%)',
                width: RING_TILE_WIDTH
              }}
            >
              <RingTile
                entry={entry}
                state={connect.connections[entry.id]}
                suggested={suggested.has(entry.id)}
                unavailable={connect.unavailableReason(entry)}
                onOpen={() => connect.open(entry)}
              />
            </div>
          ))}
        </div>
      )}
      {rest.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {rest.map((entry) => (
            <ConnectTile
              key={entry.id}
              integration={entry}
              state={connect.connections[entry.id]}
              unavailableReason={connect.unavailableReason(entry)}
              onOpen={() => connect.open(entry)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function RingTile({
  entry,
  state,
  suggested,
  unavailable,
  onOpen
}: {
  entry: CatalogEntry
  state: ConnectionState | undefined
  suggested: boolean
  unavailable: string | null
  onOpen: () => void
}): React.JSX.Element {
  const connected = state?.phase === 'done'
  return (
    <button
      type="button"
      data-tile={entry.id}
      data-connected={connected}
      className="ob-tile"
      disabled={unavailable !== null}
      onClick={onOpen}
      style={
        {
          '--ob-c': colorFor(entry.id),
          width: '100%',
          textAlign: 'left',
          padding: 12,
          borderRadius: 6,
          border: `1px solid ${state?.phase === 'error' ? 'var(--err)' : 'var(--bd)'}`,
          background: 'var(--sur)',
          color: 'var(--tx)',
          fontFamily: 'var(--font-ui)',
          cursor: unavailable ? 'default' : 'pointer',
          opacity: unavailable ? 0.55 : 1
        } as React.CSSProperties
      }
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          minHeight: 38
        }}
      >
        <TileMark integration={entry} />
        <TileBadge state={state} suggested={suggested} />
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, marginTop: 10 }}>{entry.name}</div>
      <div
        style={{
          fontSize: 11.5,
          marginTop: 2,
          color: state?.phase === 'error' ? 'var(--err)' : 'var(--mut)',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }}
        title={unavailable ?? statusFor(entry, state)}
      >
        {unavailable ?? statusFor(entry, state)}
      </div>
    </button>
  )
}

function TileBadge({
  state,
  suggested
}: {
  state: ConnectionState | undefined
  suggested: boolean
}): React.JSX.Element | null {
  if (state?.phase === 'busy') return <Spinner size={12} />
  if (state?.phase === 'done')
    return (
      <span style={{ color: 'var(--ob-c)', display: 'inline-flex' }}>
        <Icons.check size={14} />
      </span>
    )
  if (state?.phase === 'error')
    return <span style={{ color: 'var(--err)', fontSize: 11, fontWeight: 500 }}>Retry</span>
  if (suggested)
    return (
      <Mono size={8.5} color="var(--acc)">
        SUGGESTED
      </Mono>
    )
  return null
}
