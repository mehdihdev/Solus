// The Live Bench signal panel arranged by the shared view: a drop-in for DeviceBenchView's
// grid (same props). Hidden and pinned cards leave the panel, cards sort by `order`, plot
// groups overlay on one chart, and a member reorders by drag or ⋯ → Move (one PATCH per drop).
// Outside the Live Bench view context it renders the plain natural order.
import { useState } from 'react'
import type { BenchSignalSeries } from '../../../lib/api/resources'
import type { ObserverEventOut } from '../../../widgets/livebench/telemetry'
import { SignalWidget } from '../SignalWidget'
import { useBenchViewContext } from './BenchViewContext'
import { GroupChart } from './GroupChart'
import { useBenchViewStore } from './useBenchView'
import {
  arrangeSignals,
  reorderOps,
  signalTarget,
  type ArrangedItem,
  type OrderedMember
} from './viewLayout'
import { displayFor } from './viewOps'

export interface ViewSignalRow {
  deviceId: string
  key: string
  series: BenchSignalSeries
  stale: boolean
}

export interface ViewSignalGridProps {
  rows: ViewSignalRow[]
  userId: string | null
  projectId: string
  windowEndMs?: number
  events: ObserverEventOut[]
  onScope: (key: string) => void
  onOpenFinding?: (findingId: string) => void
}

type Row = ViewSignalRow & { signal: string }
type Item = ArrangedItem<Row>

const itemKey = (item: Item): string =>
  item.kind === 'card' ? item.row.key : `group:${item.group}`
const itemRows = (item: Item): Row[] => (item.kind === 'card' ? [item.row] : item.rows)

export function ViewSignalGrid(props: ViewSignalGridProps): React.JSX.Element {
  const context = useBenchViewContext()
  const [dragging, setDragging] = useState<number | null>(null)
  const rows: Row[] = props.rows.map((row) => ({ ...row, signal: row.series.signal }))
  const items: Item[] = context
    ? arrangeSignals(rows, context.view).items
    : rows.map((row) => ({ kind: 'card', row, settings: displayFor(null, signalTarget(row)) }))
  const canEdit = context?.canEdit ?? false
  const move = (from: number, to: number): void => {
    if (!context) return
    const members: OrderedMember[][] = items.map((item) =>
      itemRows(item).map((row) => ({
        target: signalTarget(row),
        order: displayFor(context.view, signalTarget(row)).order
      }))
    )
    const ops = reorderOps(members, from, to)
    if (ops.length) void useBenchViewStore.getState().setDisplay(context.projectId, ops)
  }
  return (
    <div className="bench-signal-grid">
      {items.map((item, index) => (
        <div
          key={itemKey(item)}
          data-testid="view-grid-item"
          draggable={canEdit}
          onDragStart={() => setDragging(index)}
          onDragOver={(event) => canEdit && event.preventDefault()}
          onDrop={() => {
            if (dragging !== null) move(dragging, index)
            setDragging(null)
          }}
        >
          <GridItem
            item={item}
            grid={props}
            onMove={canEdit ? (delta) => move(index, index + delta) : undefined}
          />
        </div>
      ))}
    </div>
  )
}

function GridItem({
  item,
  grid,
  onMove
}: {
  item: Item
  grid: ViewSignalGridProps
  onMove?: (delta: -1 | 1) => void
}): React.JSX.Element {
  if (item.kind === 'group')
    return <GroupChart group={item.group} members={item.rows} windowEndMs={grid.windowEndMs} />
  const { row } = item
  return (
    <>
      {row.stale && <p role="status">{row.series.signal} · STALE — waiting for telemetry</p>}
      <SignalWidget
        userId={grid.userId}
        projectId={grid.projectId}
        deviceId={row.deviceId}
        series={row.series}
        windowEndMs={grid.windowEndMs}
        events={grid.events}
        onScope={() => grid.onScope(row.key)}
        onOpenFinding={grid.onOpenFinding}
        onMove={onMove}
      />
    </>
  )
}
