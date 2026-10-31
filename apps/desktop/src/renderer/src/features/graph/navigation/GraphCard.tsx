import { memo, useEffect, useRef, useState, type PointerEvent, type ReactNode } from 'react'
import { SolusLogo } from '../../../components/ui/SolusLogo'
import type { Entity } from '../../../lib/api/resources'
import type { Point } from '../../../lib/api/workspace'
import { markAwaited, markSafely } from '../../../lib/perf/marks'
import { integrationLogo } from '../../onboarding/integrationLogos'
import type { FindingBadge } from '../useFindings'
import { boundedPoint, CARD_HEIGHT, CARD_WIDTH } from './layout'
import './GraphCard.css'

/** Pixels a pointer must travel before a press on the card body becomes a drag. */
const DRAG_THRESHOLD = 4
/** Presses here never start a body drag: editors, embedded content, the ⋮⋮ handle. */
const NO_BODY_DRAG =
  'input, textarea, select, [contenteditable], .graph-node-content, .graph-node-drag, .graph-child-previews'

interface DragStart {
  pointer: number
  client: Point
  original: Point
  scale: number
}

function dragPoint(start: DragStart, event: PointerEvent): Point {
  return boundedPoint({
    x: start.original.x + (event.clientX - start.client.x) / start.scale,
    y: start.original.y + (event.clientY - start.client.y) / start.scale
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
          original: point,
          scale:
            Number(
              event.currentTarget
                .closest<HTMLElement>('.graph-level')
                ?.style.getPropertyValue('zoom')
            ) || 1
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
  /** SOL looked at this entity this turn (SOLUSDEV-321 P1-T6): the card glows for a few seconds. */
  highlighted?: boolean
  childCount: number
  onRevealChild?: (id: string) => void
  childPreviews?: readonly { entity: Entity; childCount: number }[]
  /** Open findings touching this entity (SOLUSDEV-320); absent → no badge. */
  finding?: FindingBadge | null
  onSelect: (entity: Entity) => void
  onEnter: (entity: Entity) => void
  onBack: () => void
  onPreview: (entityId: string, point: Point) => void
  onMove: (entityId: string, point: Point) => void
  onContextMenu?: (event: React.MouseEvent, entity: Entity) => void
  renderContent?: (entity: Entity) => ReactNode
}

/** A cluster card: a header strip (mark · name · grip), a body of child chips or the
 *  node's own content, and a mono footer with the real descendant count. Positions
 *  stay world coordinates; only the presentation follows the design template. */
export const GraphCard = memo(function GraphCard(props: GraphCardProps): React.JSX.Element {
  const { entity, point, offset, focused, highlighted, childCount, onBack } = props
  const { onContextMenu, renderContent } = props
  const onPreview = (next: Point): void => props.onPreview(entity.id, next)
  const onMove = (next: Point): void => props.onMove(entity.id, next)
  const onSelect = (): void => {
    markSafely('ws:select_clicked')
    props.onSelect(entity)
  }
  const onEnter = (): void => props.onEnter(entity)
  const content = renderContent?.(entity)
  const previews = props.childPreviews?.slice(0, 4) ?? []
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
      className={`graph-node${focused ? ' graph-node-focused' : ''}${highlighted ? ' graph-node-highlighted' : ''}${body.dragging ? ' graph-node-dragging' : ''}`}
      data-testid={`graph-node-${entity.id}`}
      data-node-id={entity.id}
      data-domain={entity.domain}
      data-unbound={cardUnbound(entity)}
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
        <CardMark entity={entity} />
        <button
          type="button"
          className="graph-node-select"
          aria-label={`Select ${entity.name}`}
          aria-pressed={focused}
          title={entity.name}
          onClick={unlessDragged(onSelect)}
          onDoubleClick={unlessDragged(onEnter)}
          onKeyDown={(event) => navigateCardKey(event, onEnter, onBack)}
        >
          <strong>
            <FindingMark finding={props.finding} />
            {entity.name}
          </strong>
        </button>
        <NodeDrag entity={entity} point={point} onPreview={onPreview} onMove={onMove} />
      </div>
      <CardBody {...props} previews={previews} content={content} unlessDragged={unlessDragged} />
      <div className="graph-node-footer">
        <span>{childCount > 0 ? 'double-click to zoom' : ''}</span>
        {childCount > 0 ? (
          <button
            type="button"
            onClick={unlessDragged(onEnter)}
            aria-label={`Zoom into ${entity.name}`}
          >
            {childCount} node{childCount === 1 ? '' : 's'}
          </button>
        ) : (
          <span>no nodes inside</span>
        )}
      </div>
    </article>
  )
})

type Guard = (action: () => void) => (event: React.MouseEvent) => void

/** Child chips (up to four) or, for a leaf, the mono meta line; then any embedded content. */
function CardBody({
  entity,
  previews,
  content,
  unlessDragged,
  onRevealChild,
  onSelect,
  onEnter
}: Pick<GraphCardProps, 'entity' | 'onRevealChild' | 'onSelect' | 'onEnter'> & {
  previews: readonly { entity: Entity; childCount: number }[]
  content: ReactNode
  unlessDragged: Guard
}): React.JSX.Element {
  const open = (child: Entity) => (): void => {
    if (onRevealChild) onRevealChild(child.id)
    else {
      onSelect(child)
      onEnter(child)
    }
  }
  return (
    <div className="graph-node-body">
      {previews.length > 0 ? (
        <div className="graph-child-previews">
          {previews.map(({ entity: child, childCount: inside }) => (
            <button
              type="button"
              key={child.id}
              aria-label={`Open ${child.name}`}
              data-domain={child.domain}
              onClick={unlessDragged(open(child))}
            >
              <strong>
                <i className="graph-domain-dot" aria-hidden="true" />
                {child.name}
              </strong>
              <span>
                {inside} inside{inside > 0 ? ' — keep zooming' : ''}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <span className="graph-node-meta">{cardMeta(entity)}</span>
      )}
      {content != null && <div className="graph-node-content">{content}</div>}
    </div>
  )
}

/** The 34px tile: the Solus mark for `.solus`, a provider logo for an account anchor
 *  (letter-less fallback is the domain dot), otherwise the domain dot. */
function CardMark({ entity }: { entity: Entity }): React.JSX.Element {
  const provider = entity.properties?.provider
  const logo =
    entity.type === 'integration_account' && typeof provider === 'string'
      ? integrationLogo(provider)
      : null
  return (
    <span className="graph-node-mark" aria-hidden="true">
      {entity.type === 'solus_config' ? (
        <SolusLogo size={18} />
      ) : logo ? (
        <img src={logo} alt="" />
      ) : (
        <i className="graph-domain-dot" />
      )}
    </span>
  )
}

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
          original: point,
          scale:
            Number(
              event.currentTarget
                .closest<HTMLElement>('.graph-level')
                ?.style.getPropertyValue('zoom')
            ) || 1
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
      ⋮⋮
    </button>
  )
}

/** Arrow keys walk levels; Escape belongs to the navigator (panel first, then up). */
function navigateCardKey(
  event: React.KeyboardEvent,
  onEnter: () => void,
  onBack: () => void
): void {
  if (event.key === 'ArrowRight') {
    event.preventDefault()
    onEnter()
  }
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    onBack()
  }
}

function FindingMark({ finding }: { finding?: FindingBadge | null }): React.JSX.Element | null {
  if (!finding) return null
  const { severity, count } = finding
  return (
    <span
      className="graph-finding-badge"
      data-severity={severity}
      title={`${count} open finding${count === 1 ? '' : 's'}, worst: ${severity}`}
    >
      {count}
    </span>
  )
}

function cardUnbound(entity: Entity): boolean | undefined {
  return (
    entity.properties?.binding_status === 'unbound' ||
    entity.properties?.status === 'pending' ||
    undefined
  )
}
function cardType(entity: Entity): string {
  return entity.type === 'solus_config' ? 'root + project' : entity.type.replaceAll('_', ' ')
}
/** The mono meta line: `TYPE · PROVIDER` (uppercased by the stylesheet), nothing invented. */
function cardMeta(entity: Entity): string {
  const provider = entity.properties?.provider
  return [cardType(entity), typeof provider === 'string' && provider ? provider : null]
    .filter((value): value is string => value !== null)
    .join(' · ')
}
