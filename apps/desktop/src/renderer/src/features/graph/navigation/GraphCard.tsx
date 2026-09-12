import { memo, useEffect, useRef, useState, type PointerEvent, type ReactNode } from 'react'
import type { Entity } from '../../../lib/api/resources'
import type { Point } from '../../../lib/api/workspace'
import { markAwaited, markSafely } from '../../../lib/perf/marks'
import { boundedPoint, CARD_HEIGHT, CARD_WIDTH } from './layout'

/** Pixels a pointer must travel before a press on the card body becomes a drag. */
const DRAG_THRESHOLD = 4
/** Presses here never start a body drag: editors, embedded content, the ⠿ handle. */
const NO_BODY_DRAG =
  'input, textarea, select, [contenteditable], .graph-node-content, .graph-node-drag'

interface DragStart {
  pointer: number
  client: Point
  original: Point
}

function dragPoint(start: DragStart, event: PointerEvent): Point {
  return boundedPoint({
    x: start.original.x + event.clientX - start.client.x,
    y: start.original.y + event.clientY - start.client.y
  })
}

/** Whole-card drag: a press anywhere on the body arms; movement past the
 *  threshold drags; the click that follows a drag is swallowed so a drop never
 *  doubles as a select. A press that never moved leaves click/double-click alone. */
function useBodyDrag(
  point: Point,
  onPreview: (point: Point) => void,
  onMove: (point: Point) => void
): {
  dragging: boolean
  dragged: React.RefObject<boolean>
  handlers: Pick<
    React.HTMLAttributes<HTMLElement>,
    'onPointerDown' | 'onPointerMove' | 'onPointerUp' | 'onPointerCancel'
  >
} {
  const start = useRef<DragStart | null>(null)
  const dragged = useRef(false)
  const [dragging, setDragging] = useState(false)
  const finish = (): void => {
    start.current = null
    setDragging(false)
  }
  return {
    dragging,
    dragged,
    handlers: {
      onPointerDown: (event) => {
        if (start.current) return // a second pointer never hijacks a drag in progress
        dragged.current = false
        if (event.button !== 0 || (event.target as Element).closest(NO_BODY_DRAG)) return
        start.current = {
          pointer: event.pointerId,
          client: { x: event.clientX, y: event.clientY },
          original: point
        }
      },
      onPointerMove: (event) => {
        const begun = start.current
        if (begun?.pointer !== event.pointerId) return
        if (!dragged.current) {
          const travelled = Math.hypot(
            event.clientX - begun.client.x,
            event.clientY - begun.client.y
          )
          if (travelled <= DRAG_THRESHOLD) return
          dragged.current = true
          setDragging(true)
          event.currentTarget.setPointerCapture?.(event.pointerId)
        }
        onPreview(dragPoint(begun, event))
      },
      onPointerUp: (event) => {
        const begun = start.current
        if (begun?.pointer !== event.pointerId) return
        if (dragged.current) {
          const next = dragPoint(begun, event)
          onPreview(next)
          onMove(next)
          event.currentTarget.releasePointerCapture?.(event.pointerId)
        }
        finish()
      },
      onPointerCancel: (event) => {
        if (start.current?.pointer !== event.pointerId) return
        if (dragged.current) onPreview(start.current.original)
        finish()
      }
    }
  }
}

/** Handlers take the entity (or its id) so the navigator can pass one stable
 *  function to every card — the memo below then re-renders only the card whose
 *  own props changed (SOLUSDEV-250 P6). */
interface GraphCardProps {
  entity: Entity
  point: Point
  offset: Point
  focused: boolean
  childCount: number
  onSelect: (entity: Entity) => void
  onEnter: (entity: Entity) => void
  onBack: () => void
  onPreview: (entityId: string, point: Point) => void
  onMove: (entityId: string, point: Point) => void
  onContextMenu?: (event: React.MouseEvent, entity: Entity) => void
  renderContent?: (entity: Entity) => ReactNode
}

export const GraphCard = memo(function GraphCard(props: GraphCardProps): React.JSX.Element {
  const { entity, point, offset, focused, childCount, onBack, onContextMenu, renderContent } = props
  const onPreview = (next: Point): void => props.onPreview(entity.id, next)
  const onMove = (next: Point): void => props.onMove(entity.id, next)
  const onSelect = (): void => {
    markSafely('ws:select_clicked')
    props.onSelect(entity)
  }
  const onEnter = (): void => props.onEnter(entity)
  const content = renderContent?.(entity)
  // The card of a robot the rail just confirmed is on screen: close the measure.
  useEffect(() => {
    markAwaited('hw:node_visible', entity.id)
  }, [entity.id])
  const body = useBodyDrag(point, onPreview, onMove)
  // A keyboard activation (detail 0) is never the click that follows a drag.
  const unlessDragged =
    (action: () => void) =>
    (event: React.MouseEvent): void => {
      if (!body.dragged.current || event.detail === 0) action()
    }

  return (
    <article
      className={`graph-node${focused ? ' graph-node-focused' : ''}${body.dragging ? ' graph-node-dragging' : ''}`}
      data-testid={`graph-node-${entity.id}`}
      data-node-id={entity.id}
      data-domain={entity.domain}
      data-x={point.x}
      data-y={point.y}
      style={{
        left: point.x - offset.x - CARD_WIDTH / 2,
        top: point.y - offset.y - CARD_HEIGHT / 2,
        width: CARD_WIDTH,
        height: CARD_HEIGHT
      }}
      onContextMenu={(event) => onContextMenu?.(event, entity)}
      {...body.handlers}
    >
      <div className="graph-node-heading">
        <span className="graph-node-domain">{entity.domain}</span>
        <NodeDrag entity={entity} point={point} onPreview={onPreview} onMove={onMove} />
      </div>
      <button
        type="button"
        className="graph-node-select"
        aria-label={`Select ${entity.name}`}
        aria-pressed={focused}
        title={entity.name}
        onClick={unlessDragged(onSelect)}
        onDoubleClick={unlessDragged(onEnter)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowRight') {
            event.preventDefault()
            onEnter()
          }
          if (event.key === 'ArrowLeft' || event.key === 'Escape') {
            event.preventDefault()
            onBack()
          }
        }}
      >
        <strong>{entity.name}</strong>
        <span>{entity.type.replaceAll('_', ' ')}</span>
      </button>
      {content != null && <div className="graph-node-content">{content}</div>}
      <div className="graph-node-footer">
        {childCount > 0 ? (
          <button
            type="button"
            onClick={unlessDragged(onEnter)}
            aria-label={`Zoom into ${entity.name}`}
          >
            {childCount} inside <span aria-hidden="true">↗</span>
          </button>
        ) : (
          <span>Leaf node</span>
        )}
      </div>
    </article>
  )
})

function NodeDrag({
  entity,
  point,
  onPreview,
  onMove
}: Pick<GraphCardProps, 'entity' | 'point'> & {
  onPreview: (point: Point) => void
  onMove: (point: Point) => void
}): React.JSX.Element {
  const drag = useRef<DragStart | null>(null)
  const handlePoint = (event: PointerEvent): Point =>
    drag.current ? dragPoint(drag.current, event) : point

  return (
    <button
      type="button"
      className="graph-node-drag"
      aria-label={`Move ${entity.name}`}
      title="Drag to arrange. Arrow keys move this node."
      onPointerDown={(event) => {
        if (event.button !== 0) return
        event.preventDefault()
        event.currentTarget.setPointerCapture?.(event.pointerId)
        drag.current = {
          pointer: event.pointerId,
          client: { x: event.clientX, y: event.clientY },
          original: point
        }
      }}
      onPointerMove={(event) => {
        if (drag.current?.pointer === event.pointerId) onPreview(handlePoint(event))
      }}
      onPointerUp={(event) => {
        if (drag.current?.pointer !== event.pointerId) return
        const next = handlePoint(event)
        drag.current = null
        onPreview(next)
        onMove(next)
        event.currentTarget.releasePointerCapture?.(event.pointerId)
      }}
      onPointerCancel={() => {
        if (drag.current) onPreview(drag.current.original)
        drag.current = null
      }}
      onKeyDown={(event) => {
        const deltas: Record<string, Point> = {
          ArrowLeft: { x: -40, y: 0 },
          ArrowRight: { x: 40, y: 0 },
          ArrowUp: { x: 0, y: -40 },
          ArrowDown: { x: 0, y: 40 }
        }
        const delta = deltas[event.key]
        if (!delta) return
        event.preventDefault()
        const next = boundedPoint({ x: point.x + delta.x, y: point.y + delta.y })
        onPreview(next)
        onMove(next)
      }}
    >
      ⠿
    </button>
  )
}
