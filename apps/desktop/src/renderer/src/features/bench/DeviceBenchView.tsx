import { useEffect, useState } from 'react'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../graph/workspaceSession'
import { useAuthStore } from '../../store/authStore'
import { useSettingsStore } from '../../store/settingsStore'
import { getSignalAnomalies } from './signalAnomalies'
import type { ObserverEventOut } from '../../widgets/livebench/telemetry'
import { partitionSignals } from './primarySignals'
import { SignalWidget } from './SignalWidget'
import { retainedDevices } from './retainedSignals'
import { useBenchRealtimeData } from './BenchRealtime'
import { getBenchDeviceRecent, type BenchDeviceRecent } from '../../lib/api/resources'
import { latestOf, streamState } from '../../widgets/livebench/telemetry'
import './bench.css'

export const POLL_MS = 2500
const RECENT_LIMIT = 512
const WINDOW_MS = 8000
interface BatchData {
  readonly scope: string
  readonly byId: Readonly<Record<string, BenchDeviceRecent>>
  readonly eventsFailed: boolean
  readonly events: readonly ObserverEventOut[]
  readonly fetchedAtMs: number
}
function useDeviceBatch(
  projectId: string,
  visible: readonly string[],
  focusEntityId?: string,
  paused = false
): { current: BatchData | null; failedScope: string | null; scope: string } {
  const realtime = useBenchRealtimeData(projectId)
  const { streamReady, streamDevices } = streamSelection(realtime, visible, focusEntityId)
  const [data, setData] = useState<BatchData | null>(null)
  const [failedScope, setFailedScope] = useState<string | null>(null)
  // Stable dependency for the id list — effects compare by value, not array.
  const visibleKey = [...new Set(visible)].sort().join('\n')
  const account = useAuthStore((state) => state.user?.email ?? null)
  const generation = useWorkspaceSessionGeneration()
  const scope = JSON.stringify([account, projectId, focusEntityId, generation])
  const current =
    !realtime?.blocked && data?.scope === scope
      ? {
          ...data,
          byId: Object.fromEntries(Object.entries(data.byId).filter(([id]) => visible.includes(id)))
        }
      : null

  useEffect(() => {
    if (!streamReady || paused || !streamDevices || !realtime) return
    setData((previous) => ({
      scope,
      events: realtime.events,
      eventsFailed: realtime.eventsFailed,
      byId: retainedDevices(
        streamDevices.filter((d) => visibleKey.split('\n').includes(d.device_id)),
        previous?.scope === scope ? previous.byId : {},
        realtime.receivedAt
      ),
      fetchedAtMs: realtime.clock
    }))
    setFailedScope(null)
  }, [streamReady, streamDevices, realtime, scope, paused, visibleKey])

  useEffect(() => {
    const ids = visibleKey.split('\n').filter(Boolean)
    if (ids.length === 0 || paused || streamReady || realtime?.blocked) return
    let live = true
    let inFlight = false
    let eventsInFlight = false
    let eventSnapshot: ObserverEventOut[] | null = null
    const active = (): boolean => live && workspaceSessionGeneration() === generation
    async function poll(): Promise<void> {
      if (inFlight) return
      inFlight = true
      try {
        const devices: BenchDeviceRecent[] = []
        // The route bounds each request to 16 IDs; focus must also find devices
        // beyond the overview's panel cap. Stop obsolete batches immediately.
        for (let offset = 0; offset < ids.length; offset += 16) {
          devices.push(
            ...(await getBenchDeviceRecent(projectId, ids.slice(offset, offset + 16), {
              limit: RECENT_LIMIT,
              focusEntityId
            }))
          )
          if (!active()) return
        }
        if (!active()) return
        const fetchedAtMs = Date.now()
        setData((previous) => ({
          scope,
          events: eventSnapshot ?? [],
          eventsFailed: eventSnapshot === null,
          byId: retainedDevices(
            devices,
            previous?.scope === scope ? previous.byId : {},
            fetchedAtMs
          ),
          fetchedAtMs
        }))
        setFailedScope(null)
      } catch {
        if (active()) setFailedScope(scope)
      } finally {
        inFlight = false
      }
    }
    async function pollEvents(): Promise<void> {
      if (eventsInFlight) return
      eventsInFlight = true
      try {
        const events = await getSignalAnomalies(projectId).catch(() => null)
        if (!active()) return
        eventSnapshot = events
        setData((previous) =>
          previous?.scope === scope
            ? {
                ...previous,
                events: events ?? [],
                eventsFailed: events === null
              }
            : previous
        )
      } finally {
        eventsInFlight = false
      }
    }
    void pollEvents()
    const eventInterval = setInterval(() => void pollEvents(), 5000)
    void poll()
    const interval = setInterval(() => void poll(), POLL_MS)
    return () => {
      live = false
      clearInterval(interval)
      clearInterval(eventInterval)
    }
  }, [
    projectId,
    visibleKey,
    scope,
    focusEntityId,
    generation,
    paused,
    streamReady,
    realtime?.blocked
  ])

  return { current, failedScope: realtime?.blocked ? scope : failedScope, scope }
}

function FocusStatus({
  focused,
  failed,
  loaded,
  empty
}: {
  focused: boolean
  failed: boolean
  loaded: boolean
  empty: boolean
}): React.JSX.Element | null {
  const guide = useSettingsStore((state) => state.solMode === 'Guide')
  if (!focused) return null
  if (failed) return <p role="alert">Focused telemetry is unavailable.</p>
  if (!loaded) return <p role="status">Loading focused telemetry…</p>
  if (!empty) return null
  return (
    <p role="status">
      {guide
        ? 'No confirmed device mapping for this focus. Clear Workspace focus to see all devices.'
        : 'No mapped devices. Clear focus to see all devices.'}
    </p>
  )
}

interface Props {
  projectId: string
  deviceIds: readonly string[]
  focusEntityId?: string
  paused?: boolean
  onStreamChange?: (live: boolean) => void
  onConfirmBoard?: () => void
  robotCount?: number
}
export function DeviceBenchView({
  projectId,
  deviceIds,
  focusEntityId,
  paused = false,
  onStreamChange,
  onConfirmBoard,
  robotCount
}: Props): React.JSX.Element {
  const deviceKey = deviceIds.join('\n')
  const [lastDevices, setLastDevices] = useState(deviceKey)
  if (!paused && lastDevices !== deviceKey) setLastDevices(deviceKey)
  const visibleDevices = paused ? lastDevices.split('\n').filter(Boolean) : deviceIds
  const { current, failedScope, scope } = useDeviceBatch(
    projectId,
    visibleDevices,
    focusEntityId,
    paused
  )
  const userId = useAuthStore((state) => state.user?.email ?? null)
  const [selection, setSelection] = useState<{ scope: string; key: string } | null>(null)
  const rows = signalRows(current)
  const { primary, diagnostics } = partitionSignals(rows)
  const selected = selectedSignal(selection, scope, rows)
  const live = hasLiveSignal(current, rows, failedScope === scope)
  useEffect(() => {
    onStreamChange?.(live)
  }, [live, onStreamChange, current?.fetchedAtMs])
  const displayed = selected ? rows.filter((row) => row.key === selected) : primary
  const events = signalEvents(current, rows)
  const placeholders = rows.some(hasPlaceholder)
  const windowEndMs = current?.fetchedAtMs
  return (
    <section className="bench-signals" aria-label="Live signals">
      <div className="bench-section-heading">
        <span>{primary.length} SIGNALS · CLICK TO SCOPE · CLICK NAME TO RENAME</span>
        <span>WINDOW 8 S</span>
      </div>
      <DeviceChips current={current} />
      <SignalsStatus
        focused={Boolean(focusEntityId)}
        failed={failedScope === scope}
        current={current}
        visibleDevices={visibleDevices}
        empty={rows.length === 0}
      />
      {selected && (
        <button className="bench-text-button" onClick={() => setSelection(null)}>
          Show all signals
        </button>
      )}
      <SignalGrid
        rows={displayed}
        userId={userId}
        projectId={projectId}
        windowEndMs={windowEndMs}
        events={events}
        onScope={(key) => setSelection({ scope, key })}
      />
      <Diagnostics
        scope={scope}
        selected={selected}
        rows={diagnostics}
        userId={userId}
        projectId={projectId}
        windowEndMs={windowEndMs}
        events={events}
        onScope={(key) => setSelection({ scope, key })}
      />
      <PlaceholderBanner visible={placeholders} onConfirmBoard={onConfirmBoard} />
      <Reasoning
        failed={failedScope === scope}
        current={current}
        events={events}
        count={rows.filter((row) => !row.stale).length}
        robotCount={robotCount}
      />
    </section>
  )
}

function SignalsStatus(props: React.ComponentProps<typeof DeviceStatus>): React.JSX.Element {
  return (
    <>
      <FocusStatus
        focused={props.focused}
        failed={props.failed}
        loaded={props.current !== null}
        empty={props.empty}
      />
      <DeviceStatus {...props} />
    </>
  )
}

function PlaceholderBanner({
  visible,
  onConfirmBoard
}: {
  visible: boolean
  onConfirmBoard?: () => void
}): React.JSX.Element | null {
  if (!visible) return null
  return (
    <div className="bench-placeholder-banner">
      Names and units are placeholders — the board hasn&apos;t told me what these pins drive, and I
      won&apos;t guess. Rename them inline, or{' '}
      <button
        className="bench-text-button"
        aria-label="Open hardware to confirm board identity"
        onClick={onConfirmBoard}
        disabled={!onConfirmBoard}
      >
        open hardware to confirm board identity
      </button>{' '}
      to get real names.
    </div>
  )
}

function Diagnostics({
  scope,
  selected,
  ...grid
}: React.ComponentProps<typeof SignalGrid> & {
  scope: string
  selected: string | null
}): React.JSX.Element | null {
  const [openScope, setOpenScope] = useState<string | null>(null)
  const open = openScope === scope
  if (selected || !grid.rows.length) return null
  return (
    <div>
      <button
        className="bench-text-button"
        aria-expanded={open}
        onClick={() => setOpenScope(open ? null : scope)}
      >
        Diagnostics · {grid.rows.length} signals
      </button>
      {open && <SignalGrid {...grid} />}
    </div>
  )
}

function SignalGrid({
  rows,
  userId,
  projectId,
  windowEndMs,
  events,
  onScope
}: {
  rows: SignalRow[]
  userId: string | null
  projectId: string
  windowEndMs?: number
  events: ObserverEventOut[]
  onScope: (key: string) => void
}): React.JSX.Element {
  return (
    <div className="bench-signal-grid">
      {rows.map((row) => (
        <div key={row.key}>
          {row.stale && <p role="status">{row.series.signal} · STALE — waiting for telemetry</p>}
          <SignalWidget
            userId={userId}
            projectId={projectId}
            deviceId={row.deviceId}
            series={row.series}
            windowEndMs={windowEndMs}
            events={events}
            onScope={() => onScope(row.key)}
          />
        </div>
      ))}
    </div>
  )
}

interface SignalRow {
  deviceId: string
  key: string
  series: BenchDeviceRecent['signals'][number]
  stale: boolean
}
function signalRows(current: BatchData | null): SignalRow[] {
  return Object.values(current?.byId ?? {}).flatMap((device) =>
    device.signals.flatMap((series) => {
      const points = series.points.filter((point) => {
        const age = (current?.fetchedAtMs ?? 0) - Date.parse(point.timestamp)
        return age >= 0 && age <= WINDOW_MS
      })
      const retained = points.length ? points : series.points.slice(-1)
      return retained.length
        ? [
            {
              deviceId: device.device_id,
              key: JSON.stringify([device.device_id, series.signal]),
              series: { ...series, points: retained },
              stale: !points.length
            }
          ]
        : []
    })
  )
}
function selectedSignal(
  selection: { scope: string; key: string } | null,
  scope: string,
  rows: SignalRow[]
): string | null {
  return selection?.scope === scope && rows.some((row) => row.key === selection.key)
    ? selection.key
    : null
}
function signalEvents(current: BatchData | null, rows: SignalRow[]): ObserverEventOut[] {
  return (current?.events ?? []).filter(
    (event) =>
      (event.kind === 'stream_gap'
        ? Object.hasOwn(current?.byId ?? {}, event.device_id)
        : rows.some(
            (row) => row.deviceId === event.device_id && row.series.signal === event.signal
          )) &&
      Date.parse(event.at) >= (current?.fetchedAtMs ?? 0) - WINDOW_MS &&
      Date.parse(event.at) <= (current?.fetchedAtMs ?? 0)
  )
}
function hasPlaceholder(row: SignalRow): boolean {
  return (
    !row.series.points.at(-1)?.unit ||
    /^(?:PWM|ADC|GPIO|pin|channel)[-_ ]?\d+$/i.test(row.series.signal)
  )
}
function DeviceStatus({
  failed,
  focused,
  current,
  visibleDevices,
  empty
}: {
  failed: boolean
  focused: boolean
  current: BatchData | null
  visibleDevices: readonly string[]
  empty: boolean
}): React.JSX.Element {
  return (
    <>
      {!focused && (
        <DeviceMessages
          failed={failed}
          current={current}
          visibleDevices={visibleDevices}
          empty={empty}
        />
      )}
      {visibleDevices.length === 0 && (
        <div className="bench-empty">Connected hardware signals appear here automatically.</div>
      )}
    </>
  )
}
function Reasoning({
  failed,
  current,
  events,
  count,
  robotCount
}: {
  failed: boolean
  current: BatchData | null
  events: ObserverEventOut[]
  count: number
  robotCount?: number
}): React.JSX.Element {
  return (
    <>
      <div className="bench-section-heading bench-reasoning-heading">
        LIVE REASONING · SOL WATCHES THE RUN
      </div>
      {failed ? (
        <p role="status" className="bench-finding">
          Current telemetry is unavailable. Retained values are stale; current health is unknown.
        </p>
      ) : current?.eventsFailed ? (
        <p role="status" className="bench-finding">
          Anomaly evidence is unavailable.
        </p>
      ) : events.length ? (
        events.map((event, index) => (
          <article
            className="bench-finding"
            key={`${event.device_id}:${event.signal}:${event.at}:${index}`}
          >
            <strong>{event.kind.replaceAll('_', ' ')}</strong>
            <p>
              {event.signal} · {event.device_id}
            </p>
            <small>
              Observed at {event.at}. This observation does not establish a cross-domain cause.
            </small>
          </article>
        ))
      ) : (
        <article className="bench-finding">
          <strong>
            {count && current ? '✓ Nothing out of range' : 'Waiting for signal evidence'}
          </strong>
          <p>
            Watching {count} signals
            {robotCount === undefined ? '' : ` across ${robotCount} robots`}. Findings appear here
            as headline → explanation → detail when a cause spans domains.
          </p>
          <small>
            {count && current
              ? 'No anomalies reported in the current telemetry window.'
              : 'No hardware state is inferred from an empty stream.'}
          </small>
        </article>
      )}
    </>
  )
}

function hasLiveSignal(current: BatchData | null, rows: SignalRow[], failed: boolean): boolean {
  return (
    !failed &&
    rows.some((row) => streamState(latestOf([row.series]), current?.fetchedAtMs ?? 0) === 'live')
  )
}
function DeviceMessages({
  failed,
  current,
  visibleDevices,
  empty
}: {
  failed: boolean
  current: BatchData | null
  visibleDevices: readonly string[]
  empty: boolean
}): React.JSX.Element {
  return (
    <>
      {' '}
      {failed && <p role="alert">Telemetry is unavailable for {visibleDevices.join(', ')}.</p>}
      {!current && visibleDevices.length > 0 && !failed && (
        <p role="status">Connecting to the bench…</p>
      )}
      {current && empty && (
        <p role="status">
          No recent values from {visibleDevices.join(', ')} — nothing to show yet.
        </p>
      )}
    </>
  )
}

function DeviceChips({ current }: { current: BatchData | null }): React.JSX.Element {
  return (
    <div className="bench-device-chips">
      {Object.values(current?.byId ?? {}).map((device) => (
        <span key={device.device_id}>{device.device_id}</span>
      ))}
    </div>
  )
}

function streamSelection(
  realtime: ReturnType<typeof useBenchRealtimeData>,
  visible: readonly string[],
  focusEntityId?: string
): { streamReady: boolean; streamDevices: BenchDeviceRecent[] | null | undefined } {
  const streamReady =
    !!realtime?.ready &&
    visible.every((id) => realtime.devices.some((device) => device.device_id === id))
  const streamDevices = !focusEntityId
    ? realtime?.devices
    : realtime?.focusId === focusEntityId
      ? realtime.focused
      : null
  return { streamReady, streamDevices }
}
