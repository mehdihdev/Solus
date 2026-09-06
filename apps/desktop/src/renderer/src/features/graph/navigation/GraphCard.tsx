import { useRef, type PointerEvent, type ReactNode } from 'react'
import type { Entity } from '../../../lib/api/resources'
import type { Point } from '../../../lib/api/workspace'
import { boundedPoint, CARD_HEIGHT, CARD_WIDTH } from './layout'

interface GraphCardProps {
  entity: Entity
  point: Point
  offset: Point
  focused: boolean
  childCount: number
  onSelect: () => void
  onEnter: () => void
  onBack: () => void
  onPreview: (point: Point) => void
  onMove: (point: Point) => void
  onContextMenu?: (event: React.MouseEvent, entity: Entity) => void
  content?: ReactNode
}

export function GraphCard(props: GraphCardProps): React.JSX.Element {
  const {
    entity,
    point,
    offset,
    focused,
    childCount,
    onSelect,
    onEnter,
    onBack,
    onPreview,
    onMove,
    onContextMenu,
    content
  } = props

  return (
    <article
      className={`graph-node${focused ? ' graph-node-focused' : ''}`}
      data-testid={`graph-node-${entity.id}`}
      data-node-id={entity.id}
      data-x={point.x}
      data-y={point.y}
      style={{
        left: point.x - offset.x - CARD_WIDTH / 2,
        top: point.y - offset.y - CARD_HEIGHT / 2,
        width: CARD_WIDTH,
        height: CARD_HEIGHT
      }}
      onContextMenu={(event) => onContextMenu?.(event, entity)}
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
        onClick={onSelect}
        onDoubleClick={onEnter}
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
          <button type="button" onClick={onEnter} aria-label={`Zoom into ${entity.name}`}>
            {childCount} inside <span aria-hidden="true">↗</span>
          </button>
        ) : (
          <span>Leaf node</span>
        )}
      </div>
    </article>
  )
}

function NodeDrag({
  entity,
  point,
  onPreview,
  onMove
}: Pick<GraphCardProps, 'entity' | 'point' | 'onPreview' | 'onMove'>): React.JSX.Element {
  const drag = useRef<{ pointer: number; client: Point; original: Point } | null>(null)
  const dragPoint = (event: PointerEvent): Point => {
    const start = drag.current
    return start
      ? boundedPoint({
          x: start.original.x + event.clientX - start.client.x,
          y: start.original.y + event.clientY - start.client.y
        })
      : point
  }

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
        if (drag.current?.pointer === event.pointerId) onPreview(dragPoint(event))
      }}
      onPointerUp={(event) => {
        if (drag.current?.pointer !== event.pointerId) return
        const next = dragPoint(event)
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
