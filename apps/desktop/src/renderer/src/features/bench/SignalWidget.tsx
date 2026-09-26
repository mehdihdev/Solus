import { useState } from 'react'
import type { BenchSignalSeries } from '../../lib/api/resources'
import { anomalyMarkers } from './signalAnomalies'
import type { ObserverEventOut } from '../../widgets/livebench/telemetry'
import { chartSegments } from '../../widgets/livebench/telemetry'
import { convertUnit, displayGroups, displayPoints, unitOptions } from './signalUnits'

interface Props {
  userId: string | null
  projectId: string
  deviceId: string
  series: BenchSignalSeries
  events?: readonly ObserverEventOut[]
  onScope?: () => void
  windowEndMs?: number
}
interface Preference {
  name?: string
  unit?: string
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
    return {
      name: boundedString('name' in value ? value.name : undefined, 128),
      unit: boundedString('unit' in value ? value.unit : undefined, 64)
    }
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
  windowEndMs?: number
): string[] {
  const comparable = displayPoints(series.points, unit)
  if (comparable.length < 2) return []
  const domain = {
    tMin: windowEndMs === undefined ? Date.parse(comparable[0].timestamp) : windowEndMs - 8000,
    tMax: windowEndMs ?? Date.parse(comparable[comparable.length - 1].timestamp),
    vMin: Math.min(...comparable.map((point) => point.value)),
    vMax: Math.max(...comparable.map((point) => point.value))
  }
  return displayGroups(series.points, unit).flatMap((points) =>
    chartSegments(points, 240, 48, domain)
  )
}

function signalView(
  series: BenchSignalSeries,
  preference: Preference,
  windowEndMs?: number
): {
  name: string
  unit: string | null
  options: readonly string[]
  packetUnit: string | null
  value: number | null
  segments: string[]
} {
  const latest = series.points.at(-1)
  const packetUnit = latest?.unit ?? null
  const options = unitOptions(packetUnit)
  const unit = preference.unit && options.includes(preference.unit) ? preference.unit : packetUnit
  return {
    name: preference.name || series.signal,
    unit,
    options,
    packetUnit,
    value: latest ? convertUnit(latest.value, packetUnit, unit) : null,
    segments: segmentsFor(series, unit, windowEndMs)
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
  windowEndMs
}: Props & { preferenceKey: string | null }): React.JSX.Element {
  const { preference, save, saveFailed } = usePreference(preferenceKey)
  const view = signalView(series, preference, windowEndMs)
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
        <NameEditor name={view.name} onSave={(name) => save({ ...preference, name })} />
        {view.options.length > 1 && (
          <select
            aria-label={`Display unit for ${view.name}`}
            value={view.unit ?? ''}
            onChange={(event) => save({ ...preference, unit: event.target.value })}
          >
            {view.options.map((option) => (
              <option key={option}>{option}</option>
            ))}
          </select>
        )}
      </div>
      <div className="bench-signal-value" aria-label={`${view.name} value`}>
        {view.value === null ? '—' : Number(view.value.toPrecision(6))}
        {view.unit ? (
          <span className="bench-unit">{view.unit}</span>
        ) : (
          <span className="bench-unit bench-unit-unknown">no unit</span>
        )}
      </div>
      {saveFailed && <p role="alert">This name or unit could not be saved on this machine.</p>}
      <svg
        viewBox="0 0 240 48"
        role="img"
        aria-label={`${view.name} rolling chart`}
        style={{
          width: '100%',
          height: '3.5rem',
          pointerEvents: 'none',
          color: 'var(--bench-accent)'
        }}
        preserveAspectRatio="none"
      >
        {view.segments.map((segment, index) => (
          <g key={`${index}:${segment}`}>
            <polygon
              points={`${segment} ${segment.split(' ').at(-1)?.split(',')[0]},48 ${segment.split(',')[0]},48`}
              fill="currentColor"
              opacity="0.14"
            />
            <polyline points={segment} fill="none" stroke="currentColor" strokeWidth="1.5" />
          </g>
        ))}
        {anomalyMarkers(
          events,
          deviceId,
          series.signal,
          displayPoints(series.points, view.unit),
          windowEndMs === undefined ? undefined : { start: windowEndMs - 8000, end: windowEndMs }
        ).map((marker) => (
          <line
            key={`${marker.kind}:${marker.at}`}
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
    </section>
  )
}
