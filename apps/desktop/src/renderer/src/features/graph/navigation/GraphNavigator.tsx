import { useEffect, useMemo, useRef, type CSSProperties, type ReactNode } from 'react'
import type { Entity, Relation } from '../../../lib/api/resources'
import type { Point } from '../../../lib/api/workspace'
import { GraphCard } from './GraphCard'
import { GraphLinkDrawing, GraphLinkList } from './GraphLinks'
import { HelpPopover } from './HelpPopover'
import type { NavigationStep } from './graphIndex'
import { MAX_VISIBLE_NODES, useGraphNavigation, type NavigationModel } from './useGraphNavigation'
import './navigation.css'

export { MAX_VISIBLE_NODES } from './useGraphNavigation'

export interface GraphNavigatorProps {
  projectId: string
  entities: Entity[]
  relations: Relation[]
  positions: Record<string, Point>
  focusedId: string | null
  onSelect: (entity: Entity, path: readonly NavigationStep[]) => void
  onMove: (entityId: string, point: Point) => void
  onContextMenu?: (event: React.MouseEvent, entity: Entity) => void
  renderContent?: (entity: Entity) => ReactNode
  toolbar?: ReactNode
  reveal?: { entityId: string; sequence: number }
  /** Docked at the viewport's right edge; stays put while the stage scrolls. */
  overlay?: ReactNode
}

/** Project key resets transient navigation/drag state before another tenant can render. */
export function GraphNavigator(props: GraphNavigatorProps): React.JSX.Element {
  return <Navigator key={props.projectId} {...props} />
}

function NavigationViewport({
  model,
  props
}: {
  model: NavigationModel
  props: GraphNavigatorProps
}): React.JSX.Element {
  const {
    bounds,
    location,
    viewportRef,
    key,
    links,
    points,
    parent,
    visible,
    index,
    select,
    enter,
    back,
    preview
  } = model
  const offset = useMemo(() => ({ x: bounds.left, y: bounds.top }), [bounds.left, bounds.top])
  return (
    <div className="graph-viewport" ref={viewportRef}>
      <div
        key={key}
        className="graph-level"
        data-direction={location.direction}
        style={
          {
            width: bounds.width,
            height: bounds.height,
            '--graph-origin-x': `${location.origin.x - bounds.left}px`,
            '--graph-origin-y': `${location.origin.y - bounds.top}px`
          } as CSSProperties
        }
      >
        <GraphLinkDrawing
          links={links}
          points={points}
          offset={offset}
          anchor={location.origin}
          parentName={parent?.name}
          onBack={back}
        />
        {visible.map((entity) => (
          <GraphCard
            key={entity.id}
            entity={entity}
            point={points[entity.id]}
            offset={offset}
            focused={props.focusedId === entity.id}
            childCount={index.children.get(entity.id)?.length ?? 0}
            onSelect={select}
            onEnter={enter}
            onBack={back}
            onPreview={preview}
            onMove={props.onMove}
            onContextMenu={props.onContextMenu}
            renderContent={props.renderContent}
          />
        ))}
        {visible.length === 0 && <p className="graph-empty-level">No nodes in this level.</p>}
      </div>
    </div>
  )
}

function NavigationPagination({ model }: { model: NavigationModel }): React.JSX.Element {
  const { page, level, setPage } = model
  return (
    <div className="graph-pagination">
      <span className="graph-edge-legend">
        <i /> cross-links
      </span>
      <button
        type="button"
        aria-label="Previous nodes"
        disabled={page === 0}
        onClick={() => setPage(page - 1)}
      >
        ←
      </button>
      <span aria-live="polite">
        {level.length > 0 ? page * MAX_VISIBLE_NODES + 1 : 0}–
        {Math.min((page + 1) * MAX_VISIBLE_NODES, level.length)} of {level.length}
      </span>
      <button
        type="button"
        aria-label="Next nodes"
        disabled={(page + 1) * MAX_VISIBLE_NODES >= level.length}
        onClick={() => setPage(page + 1)}
      >
        →
      </button>
    </div>
  )
}

function Navigator(props: GraphNavigatorProps): React.JSX.Element {
  const model = useGraphNavigation(props)
  useReveal(props.reveal, model)
  return (
    <section
      ref={model.rootRef}
      className="graph-navigator"
      data-testid="graph-navigator"
      data-depth={model.trail.length}
      aria-label="Project graph navigator"
    >
      <div className="graph-viewport-frame">
        <NavigationViewport model={model} props={props} />
        <div className="graph-corner graph-corner-left">{props.toolbar}</div>
        <div className="graph-corner graph-corner-right">
          <HelpPopover trail={model.trail} onOverview={() => model.go(null)} />
        </div>
        {props.overlay && <div className="graph-overlay">{props.overlay}</div>}
      </div>
      <NavigationPagination model={model} />
      <GraphLinkList
        key={model.key}
        index={model.index}
        links={model.links}
        onShow={model.showLinked}
      />
    </section>
  )
}

function useReveal(reveal: GraphNavigatorProps['reveal'], model: NavigationModel): void {
  const handled = useRef<number | null>(null)
  useEffect(() => {
    if (!reveal || handled.current === reveal.sequence) return
    const entity = model.index.entities.get(reveal.entityId)
    if (!entity) return
    handled.current = reveal.sequence
    model.showLinked(entity)
  }, [reveal, model])
}
