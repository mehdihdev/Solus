import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { ContextMenu, clampMenuPosition } from '../../../components/ui/ContextMenu'
import type { Entity, Relation } from '../../../lib/api/resources'
import type { Point } from '../../../lib/api/workspace'
import type { MoveOrigin } from '../useWorkspaceLayout'
import type { FindingsBySubject } from '../useFindings'
import { GraphBreadcrumb } from './GraphBreadcrumb'
import { GraphCard } from './GraphCard'
import { GraphLinkDrawing, type StructureLine } from './GraphLinks'
import { HelpPopover } from './HelpPopover'
import { buildNavigationIndex, type NavigationStep } from './graphIndex'
import { CARD_HEIGHT, PAD } from './layout'
import {
  EDITABLE,
  MAX_VISIBLE_NODES,
  useGraphNavigation,
  type NavigationModel
} from './useGraphNavigation'
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
  /** A drawn edge was clicked (never a synthetic projection id). */
  onSelectEdge?: (relation: Relation) => void
  selectedEdgeId?: string | null
  /** Viewport "Re-layout": clear the current level's saved positions so defaults run again. */
  onRelayout?: (levelIds: readonly string[]) => void
  /** Open findings per entity id → each card's badge (SOLUSDEV-320 P4-T3). */
  findings?: FindingsBySubject
  /** Escape outside any editor or dialog: return true to consume it (e.g. a side panel
   *  closed); otherwise the navigator goes up one level. */
  onEscape?: () => boolean
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

type ChildPreviews = ReturnType<typeof useChildPreviews>

/** Child previews per visible node, resolved against the scoped graph when one applies. */
function useChildPreviews(
  { visible, index }: NavigationModel,
  scopeRootIds: GraphNavigatorProps['scopeRootIds'],
  scopeGraph: GraphNavigatorProps['scopeGraph'],
  projectId: string
) {
  return useMemo(
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
}

function NavigationCards({
  model,
  scopeRootIds,
  offset,
  previews,
  ...props
}: GraphNavigatorProps & {
  model: NavigationModel
  offset: { x: number; y: number }
  previews: ChildPreviews
}): React.JSX.Element {
  const { visible, points, select, enter, back, preview } = model
  return (
    <>
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
          finding={props.findings?.get(entity.id) ?? null}
          onSelect={select}
          onEnter={enter}
          onBack={back}
          onPreview={preview}
          onMove={props.onMove}
          onContextMenu={props.onContextMenu}
          renderContent={props.renderContent}
        />
      ))}
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
  const { bounds, location, viewportRef, key, links, points, visible, index } = model
  const previews = useChildPreviews(model, scopeRootIds, props.scopeGraph, props.projectId)
  const offset = useMemo(() => ({ x: bounds.left, y: bounds.top }), [bounds.left, bounds.top])
  const menu = useRelayoutMenu(model, props.onRelayout)
  const structure = useStructureLines(model)
  useDragPan(viewportRef)
  return (
    <div className="graph-viewport" ref={viewportRef} onContextMenu={menu.onContextMenu}>
      {menu.element}
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
          onSelectEdge={props.onSelectEdge}
          selectedEdgeId={props.selectedEdgeId}
          structure={structure}
        />
        <NavigationCards
          {...props}
          model={model}
          scopeRootIds={scopeRootIds}
          offset={offset}
          previews={previews}
        />
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

/** Containment, drawn (design template): inside a level, one stem from the frame's top edge
 *  (the parent you zoomed out of) into a bus above the first row, with a drop into every card;
 *  at the root, the project's `.solus` hub out to the other roots. Real `contains` edges and the
 *  project's own membership — never an invented relation. */
function useStructureLines(model: NavigationModel): readonly StructureLine[] {
  const { parent, visible, points, bounds } = model
  return useMemo(() => {
    if (parent) {
      const stem = { x: bounds.left + bounds.width / 2, y: bounds.top }
      const via = bounds.top + PAD / 2
      return visible.flatMap((entity) => {
        const point = points[entity.id]
        return point ? [{ from: stem, to: { x: point.x, y: point.y - CARD_HEIGHT / 2 }, via }] : []
      })
    }
    const hub = visible.find((entity) => entity.type === 'solus_config')
    const origin = hub && points[hub.id]
    if (!hub || !origin) return []
    return visible.flatMap((entity) => {
      const point = points[entity.id]
      if (entity.id === hub.id || !point) return []
      const above = point.y < origin.y
      return [
        {
          from: { x: origin.x, y: origin.y + (above ? -CARD_HEIGHT / 2 : CARD_HEIGHT / 2) },
          to: { x: point.x, y: point.y + (above ? CARD_HEIGHT / 2 : -CARD_HEIGHT / 2) }
        }
      ]
    })
  }, [parent, visible, points, bounds])
}

/** Hold the pointer on the canvas background and drag to pan (scroll the viewport). Cards,
 *  controls and editors keep their own pointer behaviour. */
const NO_PAN = `.graph-node, ${EDITABLE}, button, a, path, .graph-suggestion`

function useDragPan(viewportRef: React.RefObject<HTMLDivElement | null>): void {
  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    let start: { id: number; x: number; y: number; left: number; top: number } | null = null
    const down = (event: PointerEvent): void => {
      if (event.button !== 0 || !(event.target instanceof Element) || event.target.closest(NO_PAN))
        return
      start = {
        id: event.pointerId,
        x: event.clientX,
        y: event.clientY,
        left: viewport.scrollLeft,
        top: viewport.scrollTop
      }
      viewport.dataset.panning = 'true'
      viewport.setPointerCapture?.(event.pointerId)
    }
    const move = (event: PointerEvent): void => {
      if (!start || start.id !== event.pointerId) return
      viewport.scrollLeft = start.left - (event.clientX - start.x)
      viewport.scrollTop = start.top - (event.clientY - start.y)
    }
    const up = (event: PointerEvent): void => {
      if (!start || start.id !== event.pointerId) return
      start = null
      delete viewport.dataset.panning
      viewport.releasePointerCapture?.(event.pointerId)
    }
    viewport.addEventListener('pointerdown', down)
    viewport.addEventListener('pointermove', move)
    viewport.addEventListener('pointerup', up)
    viewport.addEventListener('pointercancel', up)
    return () => {
      viewport.removeEventListener('pointerdown', down)
      viewport.removeEventListener('pointermove', move)
      viewport.removeEventListener('pointerup', up)
      viewport.removeEventListener('pointercancel', up)
    }
  }, [viewportRef])
}

/** Paging only when a level has more cards than fit (design: no permanent bottom bar). */
function NavigationPagination({ model }: { model: NavigationModel }): React.JSX.Element | null {
  const { page, level, setPage } = model
  if (level.length <= MAX_VISIBLE_NODES) return null
  return (
    <div className="graph-pagination">
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
  useEscapeNavigation(props.onEscape, model.back)
  const forgetDefaults = useDefaultPositions(props, model)
  const { onRelayout } = props
  const relayout = onRelayout
    ? (ids: readonly string[]): void => {
        forgetDefaults()
        onRelayout(ids)
      }
    : undefined
  return (
    <section
      ref={model.rootRef}
      className="graph-navigator"
      data-testid="graph-navigator"
      data-depth={model.trail.length}
      aria-label="Project graph navigator"
    >
      <div className="graph-viewport-frame">
        <NavigationViewport {...props} model={model} onRelayout={relayout} />
        <GraphZoomControls viewportRef={model.viewportRef} levelKey={model.key} />
        <div className="graph-corner graph-corner-left">
          {props.toolbar}
          <GraphBreadcrumb
            trail={model.trail}
            level={model.level.length}
            total={model.index.entities.size}
            onGo={model.go}
            onBack={model.back}
          />
        </div>
        <div className="graph-corner graph-corner-right">
          <HelpPopover trail={model.trail} onOverview={() => model.go(null)} />
        </div>
        {props.overlay && <div className="graph-overlay">{props.overlay}</div>}
      </div>
      <NavigationPagination model={model} />
    </section>
  )
}

/** Escape at the window: dialogs and editors win (they preventDefault or sit inside
 *  EDITABLE), then the owner may consume it (close a panel), then the level goes up. */
function useEscapeNavigation(onEscape: GraphNavigatorProps['onEscape'], back: () => boolean): void {
  const latest = useRef({ onEscape, back })
  latest.current = { onEscape, back }
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      if (event.target instanceof Element && event.target.closest(EDITABLE)) return
      if (latest.current.onEscape?.()) return
      latest.current.back()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}

function useReveal(reveal: GraphNavigatorProps['reveal'], model: NavigationModel): void {
  const handled = useRef<number | null>(null)
  useEffect(() => {
    if (!reveal || handled.current === reveal.sequence) return
    if (model.revealEntity(reveal.entityId)) handled.current = reveal.sequence
  }, [reveal, model])
}

/** Right-click on the canvas background (not a card or an editor) offers Re-layout. */
function useRelayoutMenu(
  { level }: NavigationModel,
  onRelayout: GraphNavigatorProps['onRelayout']
): { onContextMenu: (event: React.MouseEvent) => void; element: ReactNode } {
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  useEffect(() => {
    if (!menu) return
    const dismiss = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setMenu(null)
    }
    document.addEventListener('keydown', dismiss, true)
    return () => document.removeEventListener('keydown', dismiss, true)
  }, [menu])
  const onContextMenu = (event: React.MouseEvent): void => {
    if (!onRelayout || (event.target as Element).closest(`.graph-node, ${EDITABLE}`)) return
    event.preventDefault()
    setMenu(clampMenuPosition(event.clientX, event.clientY))
  }
  const element = menu && onRelayout && (
    <ContextMenu
      x={menu.x}
      y={menu.y}
      items={[{ label: 'Re-layout', onSelect: () => onRelayout(level.map(({ id }) => id)) }]}
      onClose={() => setMenu(null)}
    />
  )
  return { onContextMenu, element }
}

/** Persist only missing defaults once; dragging never triggers a rearrange. Returns the forget hook Re-layout uses. */
function useDefaultPositions(
  { persistDefaults, positions, onMove }: GraphNavigatorProps,
  { visible, points }: NavigationModel
): () => void {
  const sent = useRef(new Set<string>())
  useEffect(() => {
    if (!persistDefaults) return
    for (const entity of visible) {
      if (positions[entity.id] || sent.current.has(entity.id)) continue
      sent.current.add(entity.id)
      onMove(entity.id, points[entity.id], 'auto')
    }
  }, [persistDefaults, positions, onMove, visible, points])
  return () => sent.current.clear()
}
