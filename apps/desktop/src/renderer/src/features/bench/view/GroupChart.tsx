// One chart for a plot group (wireflow live-bench-view.md "Layout"): every member is a line
// with its own legend entry and keeps its own (team) unit when convertible. The axis range is
// shared; a member's fixed limits, when set, fix it. Names are escaped text.
import type { BenchViewLimits } from '@solus/shared-types'
import type { BenchSignalSeries } from '../../../lib/api/resources'
import { chartSegments } from '../../../widgets/livebench/telemetry'
import { displayGroups, displayPoints, limitedDomain, sharedUnit } from '../signalUnits'
import { displayFor } from './viewOps'
import { useBenchViewContext } from './BenchViewContext'

export interface GroupMember {
  deviceId: string
  series: BenchSignalSeries
}

const COLORS = ['var(--acc)', 'var(--sw)', 'var(--ee)', 'var(--me)', 'var(--rt)']
const WIDTH = 240
const HEIGHT = 64

interface Line {
  name: string
  unit: string | null
  segments: string[]
}

function memberLines(
  members: readonly GroupMember[],
  units: readonly (string | null)[],
  limits: BenchViewLimits | null,
  windowEndMs?: number
): Line[] {
  const all = members.flatMap((member, i) => displayPoints(member.series.points, units[i]))
  if (all.length < 2)
    return members.map((m, i) => ({ name: m.series.signal, unit: units[i], segments: [] }))
  const times = all.map((point) => Date.parse(point.timestamp))
  const domain = {
    tMin: windowEndMs === undefined ? Math.min(...times) : windowEndMs - 8000,
    tMax: windowEndMs ?? Math.max(...times),
    ...limitedDomain(
      all.map((point) => point.value),
      units[0] ?? null,
      limits
    )
  }
  return members.map((member, i) => ({
    name: member.series.signal,
    unit: units[i],
    segments: displayGroups(member.series.points, units[i]).flatMap((points) =>
      chartSegments(points, WIDTH, HEIGHT, domain)
    )
  }))
}

export function GroupChart({
  group,
  members,
  windowEndMs
}: {
  group: string
  members: readonly GroupMember[]
  windowEndMs?: number
}): React.JSX.Element {
  const view = useBenchViewContext()?.view ?? null
  const settings = members.map((member) =>
    displayFor(view, { kind: 'signal', device_id: member.deviceId, signal: member.series.signal })
  )
  const units = members.map((member, i) =>
    sharedUnit(member.series.points.at(-1)?.unit ?? null, settings[i].unit)
  )
  const limits = settings.find((entry) => entry.limits)?.limits ?? null
  const lines = memberLines(members, units, limits, windowEndMs)
  return (
    <section aria-label={`${group} plot group`} className="bench-signal-card">
      <div className="bench-signal-controls">
        <span className="bench-signal-name">{group}</span>
      </div>
      <ul
        style={{
          listStyle: 'none',
          margin: 0,
          padding: 0,
          display: 'flex',
          gap: 8,
          flexWrap: 'wrap'
        }}
      >
        {lines.map((line, i) => (
          <li
            key={`${members[i].deviceId}:${line.name}`}
            style={{ color: COLORS[i % COLORS.length] }}
          >
            {line.name}
            {line.unit ? ` ${line.unit}` : ''}
          </li>
        ))}
      </ul>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`${group} overlaid chart`}
        style={{ width: '100%', height: '4.5rem' }}
        preserveAspectRatio="none"
      >
        {lines.map((line, i) => (
          <g
            key={`${members[i].deviceId}:${line.name}`}
            data-testid="group-line"
            style={{ color: COLORS[i % COLORS.length] }}
          >
            {line.segments.map((segment, index) => (
              <polyline
                key={`${index}:${segment}`}
                points={segment}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
              />
            ))}
          </g>
        ))}
      </svg>
    </section>
  )
}
