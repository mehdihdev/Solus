import { useEffect, useMemo, useRef, type CSSProperties, type ReactNode } from 'react'
import type { Entity, Relation } from '../../../lib/api/resources'
import type { Point } from '../../../lib/api/workspace'
import type { MoveOrigin } from '../useWorkspaceLayout'
import { GraphCard } from './GraphCard'
import { GraphLinkDrawing, GraphLinkList } from './GraphLinks'
import { HelpPopover } from './HelpPopover'
import { buildNavigationIndex, type NavigationStep } from './graphIndex'
import { MAX_VISIBLE_NODES, useGraphNavigation, type NavigationModel } from './useGraphNavigation'
import './navigation.css'
import { useAuthStore } from '../../../store/authStore'
import { useWorkspaceSessionGeneration } from '../workspaceSession'
import { useGroupPositions } from './useGroupPositions'
import { GraphSuggestions } from './GraphSuggestions'
import { GraphZoomControls } from './GraphZoomControls'

export { MAX_VISIBLE_NODES } from './useGraphNavigation'

export interface GraphNavigatorProps {
  persistDefaults?: boolean
  onSuggestionsChanged?: () => void
  projectId: string
  entities: Entity[]
  relations: Relation[]
  positions: Record<string, Point>
  focusedId: string | null
  /** A graph projection scoped by the root entered; identities remain graph IDs. */
  scopeGraph?: (rootId: string | null) => { entities: Entity[]; relations: Relation[] }
  scopeRootIds?: readonly string[]
  onSelect: (entity: Entity, path: readonly NavigationStep[]) => void
  onMove: (entityId: string, point: Point, origin?: MoveOrigin) => void
  onContextMenu?: (event: React.MouseEvent, entity: Entity) => void
  renderContent?: (entity: Entity) => ReactNode
  toolbar?: ReactNode
  reveal?: { entityId: string; sequence: number }
  /** Docked at the viewport's right edge; stays put while the stage scrolls. */
  overlay?: ReactNode
}

/** Project key resets transient navigation/drag state before another tenant can render. */
export function GraphNavigator(props: GraphNavigatorProps): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  return <PositionedNavigator key={`${props.projectId}:${generation}`} {...props} />
}

function PositionedNavigator(props: GraphNavigatorProps): React.JSX.Element {
  const email = useAuthStore((state) => state.user?.email)
  const layout = useGroupPositions(props.projectId, email, props.positions, props.onMove)
  return (
    <>
      <Navigator {...props} positions={layout.positions} onMove={layout.move} />
      {layout.error && <p role="alert">{layout.error}</p>}
    </>
  )
}

function NavigationViewport({
  model,
  scopeRootIds,
  ...props
}: GraphNavigatorProps & {
  model: NavigationModel
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
  const { scopeGraph, projectId } = props
  const previews = useMemo(
    () =>
      new Map(
        visible.map(({ id }) => {
          const scoped = scopeRootIds?.includes(id) ? scopeGraph?.(id) : undefined
          const childIndex = scoped
            ? buildNavigationIndex(
                scoped.entities.filter(
                  (entity) => !entity.project_id || entity.project_id === projectId
                ),
                scoped.relations
              )
            : index
          return [
            id,
            (childIndex.children.get(id) ?? []).map((entity) => ({
              entity,
              childCount: childIndex.children.get(entity.id)?.length ?? 0
            }))
          ]
        })
      ),
    [index, visible, scopeRootIds, scopeGraph, projectId]
  )
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
          index={index}
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
            childCount={previews.get(entity.id)?.length ?? 0}
            onRevealChild={scopeRootIds?.includes(entity.id) ? model.revealEntity : undefined}
            childPreviews={previews.get(entity.id)}
            onSelect={select}
            onEnter={enter}
            onBack={back}
            onPreview={preview}
            onMove={props.onMove}
            onContextMenu={props.onContextMenu}
            renderContent={props.renderContent}
          />
        ))}
        {props.onSuggestionsChanged && (
          <GraphSuggestions
            projectId={props.projectId}
            visible={visible}
            points={points}
            offset={offset}
            onChanged={props.onSuggestionsChanged}
          />
        )}
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
  useDefaultPositions(props, model)
  return (
    <section
      ref={model.rootRef}
      className="graph-navigator"
      data-testid="graph-navigator"
      data-depth={model.trail.length}
      aria-label="Project graph navigator"
    >
      <div className="graph-viewport-frame">
        <NavigationViewport {...props} model={model} />
        <GraphZoomControls viewportRef={model.viewportRef} />
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
    if (model.revealEntity(reveal.entityId)) handled.current = reveal.sequence
  }, [reveal, model])
}

/** Persist only missing defaults once; dragging never triggers a rearrange. */
function useDefaultPositions(
  { persistDefaults, positions, onMove }: GraphNavigatorProps,
  { visible, points }: NavigationModel
): void {
  const sent = useRef(new Set<string>())
  useEffect(() => {
    if (!persistDefaults) return
    for (const entity of visible) {
      if (positions[entity.id] || sent.current.has(entity.id)) continue
      sent.current.add(entity.id)
      onMove(entity.id, points[entity.id], 'auto')
    }
  }, [persistDefaults, positions, onMove, visible, points])
}
