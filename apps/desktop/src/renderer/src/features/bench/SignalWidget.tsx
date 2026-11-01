import { useState } from 'react'
import type { BenchViewLimits, BenchViewTarget } from '@solus/shared-types'
import type { BenchSignalSeries } from '../../lib/api/resources'
import { useBenchViewContext } from './view/BenchViewContext'
import { displayFor, type DisplaySettings } from './view/viewOps'
import { ViewControls, type DerivedActions } from './view/ViewControls'
import { anomalyMarkers, type SignalAnomaly } from './signalAnomalies'
import { chartSegments } from '../../widgets/livebench/telemetry'
import {
  convertUnit,
  displayGroups,
  displayPoints,
  formatValue,
  limitedDomain,
  sharedUnit
} from './signalUnits'

interface Props {
  userId: string | null
  projectId: string
  deviceId: string
  series: BenchSignalSeries
  events?: readonly SignalAnomaly[]
  onScope?: () => void
  windowEndMs?: number
  /** A marker that names a finding opens it in the Findings pane (SOLUSDEV-321 P2-T7). */
  onOpenFinding?: (findingId: string) => void
  /** The shared-view target; defaults to the (deviceId, signal) pair. Derived cards pass theirs. */
  target?: BenchViewTarget
  /** Keyboard reorder, supplied by the panel that knows the siblings. */
  onMove?: (delta: -1 | 1) => void
  derived?: DerivedActions
}
type Marker = ReturnType<typeof anomalyMarkers>[number]
/** Per-user, per-machine: only the display name. The unit is the team's (bench view). */
interface Preference {
  name?: string
}

function boundedString(value: unknown, max: number): string | undefined {
  return typeof value === 'string' && value.length <= max ? value : undefined
}
function readPreference(key: string | null): Preference {
  if (!key) return {}
  try {
    const raw = localStorage.getItem(key)
    if (!raw || raw.length > 2048) return {}
    const value: unknown = JSON.parse(raw)
    if (typeof value !== 'object' || value === null) return {}
    return { name: boundedString('name' in value ? value.name : undefined, 128) }
  } catch {
    return {}
  }
}

function usePreference(key: string | null): {
  preference: Preference
  save: (next: Preference) => void
  saveFailed: boolean
} {
  const [preference, setPreference] = useState(() => readPreference(key))
  const [saveFailed, setSaveFailed] = useState(false)
  function save(next: Preference): void {
    setPreference(next)
    setSaveFailed(false)
    if (!key) return
    try {
      localStorage.setItem(key, JSON.stringify(next))
    } catch {
      setSaveFailed(true)
    }
  }
  return { preference, save, saveFailed }
}

function NameEditor({
  name,
  onSave
}: {
  name: string
  onSave: (name: string) => void
}): React.JSX.Element {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  function finish(): void {
    const next = draft.trim()
    if (next) onSave(next)
    setEditing(false)
  }
  if (!editing)
    return (
      <button
        type="button"
        className="bench-signal-name"
        title={name}
        aria-label={`Rename ${name}`}
        onClick={() => {
          setDraft(name)
          setEditing(true)
        }}
      >
        {name}
      </button>
    )
  return (
    <input
      aria-label="Signal name"
      maxLength={128}
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={finish}
      onKeyDown={(event) => {
        if (event.key === 'Enter') finish()
        if (event.key === 'Escape') setEditing(false)
      }}
    />
  )
}

function segmentsFor(
  series: BenchSignalSeries,
  unit: string | null,
  limits: BenchViewLimits | null,
  windowEndMs?: number
): string[] {
  const comparable = displayPoints(series.points, unit)
  if (comparable.length < 2) return []
  const domain = {
    tMin: windowEndMs === undefined ? Date.parse(comparable[0].timestamp) : windowEndMs - 8000,
    tMax: windowEndMs ?? Date.parse(comparable[comparable.length - 1].timestamp),
    ...limitedDomain(
      comparable.map((point) => point.value),
      unit,
      limits
    )
  }
  return displayGroups(series.points, unit).flatMap((points) =>
    chartSegments(points, 240, 48, domain)
  )
}

function signalView(
  series: BenchSignalSeries,
  preference: Preference,
  settings: DisplaySettings,
  windowEndMs?: number
): {
  name: string
  unit: string | null
  value: number | null
  segments: string[]
} {
  const latest = series.points.at(-1)
  const packetUnit = latest?.unit ?? null
  const unit = sharedUnit(packetUnit, settings.unit)
  return {
    name: preference.name || series.signal,
    unit,
    value: latest ? convertUnit(latest.value, packetUnit, unit) : null,
    segments: segmentsFor(series, unit, settings.limits, windowEndMs)
  }
}

export function SignalWidget(props: Props): React.JSX.Element {
  const scope = JSON.stringify([props.userId, props.projectId, props.deviceId, props.series.signal])
  return (
    <ScopedSignalWidget
      key={scope}
      {...props}
      preferenceKey={props.userId ? `solus.signal.v1:${scope}` : null}
    />
  )
}

function ScopedSignalWidget({
  series,
  deviceId,
  events = [],
  preferenceKey,
  onScope,
  windowEndMs,
  onOpenFinding,
  target,
  onMove,
  derived
}: Props & { preferenceKey: string | null }): React.JSX.Element {
  const { preference, save, saveFailed } = usePreference(preferenceKey)
  const context = useBenchViewContext()
  const viewTarget = target ?? { kind: 'signal', device_id: deviceId, signal: series.signal }
  const settings = displayFor(context?.view ?? null, viewTarget)
  const view = signalView(series, preference, settings, windowEndMs)
  const markers = anomalyMarkers(
    events,
    deviceId,
    series.signal,
    displayPoints(series.points, view.unit),
    windowEndMs === undefined ? undefined : { start: windowEndMs - 8000, end: windowEndMs }
  )
  return (
    <section aria-label={`${view.name} signal`} className="bench-signal-card">
      {onScope && (
        <button
          className="bench-scope-target"
          aria-label={`Scope ${view.name}`}
          onClick={onScope}
        />
      )}
      <div className="bench-signal-controls">
        {viewTarget.kind === 'derived' ? (
          <span className="bench-signal-name" title={view.name}>
            {view.name}
          </span>
        ) : (
          <NameEditor name={view.name} onSave={(name) => save({ ...preference, name })} />
        )}
        <ViewControls
          target={viewTarget}
          label={view.name}
          packetUnit={series.points.at(-1)?.unit ?? null}
          onMove={onMove}
          derived={derived}
        />
      </div>
      <SignalValue name={view.name} value={view.value} unit={view.unit} />
      {saveFailed && <p role="alert">This name could not be saved on this machine.</p>}
      <SignalChart
        name={view.name}
        segments={view.segments}
        markers={markers}
        limits={settings.limits}
        onOpenFinding={onOpenFinding}
      />
    </section>
  )
}

function SignalValue({
  name,
  value,
  unit
}: {
  name: string
  value: number | null
  unit: string | null
}): React.JSX.Element {
  return (
    <div className="bench-signal-value" aria-label={`${name} value`}>
      {value === null ? '— (no data)' : formatValue(value, unit)}
      {unit ? (
        <span className="bench-unit">{unit}</span>
      ) : (
        <span className="bench-unit bench-unit-unknown">no unit</span>
      )}
    </div>
  )
}

/** The fixed axis range is the chart's edges; mark them so a clipped line reads as clipped. */
function LimitLines({ limits }: { limits: BenchViewLimits }): React.JSX.Element {
  return (
    <>
      {[
        { label: `Axis max ${limits.max}`, y: 0.5 },
        { label: `Axis min ${limits.min}`, y: 47.5 }
      ].map(({ label, y }) => (
        <line
          key={label}
          aria-label={label}
          x1={0}
          x2={240}
          y1={y}
          y2={y}
          stroke="var(--mut)"
          strokeDasharray="2 3"
          strokeWidth="0.75"
        >
          <title>{label}</title>
        </line>
      ))}
    </>
  )
}

const markerKey = (marker: Marker): string =>
  `${marker.kind}:${marker.at}:${marker.finding_id ?? ''}`

/** The chart lets clicks fall through to the scope target; only a marker that names a finding
 *  is a control (a button over its line), and only when a findings pane can open it. */
function SignalChart({
  name,
  segments,
  markers,
  limits,
  onOpenFinding
}: {
  name: string
  segments: string[]
  markers: Marker[]
  limits: BenchViewLimits | null
  onOpenFinding?: (findingId: string) => void
}): React.JSX.Element {
  return (
    <div style={{ position: 'relative', pointerEvents: 'none' }}>
      <svg
        viewBox="0 0 240 48"
        role="img"
        aria-label={`${name} rolling chart`}
        style={{ width: '100%', height: '3.5rem', color: 'var(--bench-accent)' }}
        preserveAspectRatio="none"
      >
        {segments.map((segment, index) => (
          <g key={`${index}:${segment}`}>
            <polygon
              points={`${segment} ${segment.split(' ').at(-1)?.split(',')[0]},48 ${segment.split(',')[0]},48`}
              fill="currentColor"
              opacity="0.14"
            />
            <polyline points={segment} fill="none" stroke="currentColor" strokeWidth="1.5" />
          </g>
        ))}
        {limits && <LimitLines limits={limits} />}
        {markers.map((marker) => (
          <line
            key={markerKey(marker)}
            aria-label={`${marker.kind} at ${marker.at}`}
            x1={marker.x}
            x2={marker.x}
            y1={0}
            y2={48}
            stroke="var(--warning, #d97706)"
            strokeDasharray="3 2"
          >
            <title>
              {marker.kind} at {marker.at}
            </title>
          </line>
        ))}
      </svg>
      {onOpenFinding &&
        markers.map(({ finding_id: findingId, ...marker }) =>
          findingId ? (
            <button
              key={markerKey({ ...marker, finding_id: findingId })}
              type="button"
              aria-label={`Open finding: ${marker.kind} at ${marker.at}`}
              title={`${marker.kind} at ${marker.at} — open the finding`}
              onClick={() => onOpenFinding(findingId)}
              style={{
                position: 'absolute',
                top: 0,
                bottom: 0,
                left: `${(marker.x / 240) * 100}%`,
                marginLeft: -5,
                width: 10,
                padding: 0,
                border: 0,
                background: 'transparent',
                cursor: 'pointer',
                pointerEvents: 'auto'
              }}
            />
          ) : null
        )}
    </div>
  )
}
