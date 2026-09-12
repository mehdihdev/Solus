import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefObject
} from 'react'
import type { Entity } from '../../../lib/api/resources'
import type { Point } from '../../../lib/api/workspace'
import type { GraphNavigatorProps } from './GraphNavigator'
import {
  buildNavigationIndex,
  projectCrossLinks,
  type NavigationIndex,
  type ProjectedLink
} from './graphIndex'
import { layoutLevel, levelBounds, ORIGIN, type LevelBounds } from './layout'

export const MAX_VISIBLE_NODES = 24
const EMPTY_ENTITIES: readonly Entity[] = []
const WHEEL_TRANSITION_MS = 350
const EDITABLE =
  'input, textarea, select, [contenteditable="true"], .graph-node-content, .graph-links-list, .graph-corner, .graph-pagination'

interface Location {
  parentId: string | null
  page: number
  origin: Point
  screenAnchor: Point | null
  direction: 'in' | 'out'
  revealedId: string | null
}
interface DraftPoint {
  point: Point
  baseline: Point | undefined
}

export interface NavigationModel {
  index: NavigationIndex
  parent: Entity | undefined
  level: readonly Entity[]
  page: number
  visible: readonly Entity[]
  points: Record<string, Point>
  bounds: LevelBounds
  links: readonly ProjectedLink[]
  trail: readonly Entity[]
  location: Location
  rootRef: RefObject<HTMLElement | null>
  viewportRef: RefObject<HTMLDivElement | null>
  key: string
  select: (entity: Entity) => void
  enter: (entity: Entity) => boolean
  back: () => boolean
  go: (entity: Entity | null) => void
  setPage: (page: number) => void
  showLinked: (entity: Entity) => void
  preview: (entityId: string, point: Point) => void
}

function childrenOf(index: NavigationIndex, parentId: string | null): readonly Entity[] {
  return parentId ? (index.children.get(parentId) ?? EMPTY_ENTITIES) : index.roots
}

function usePositions(visible: readonly Entity[], positions: Record<string, Point>, anchor: Point) {
  const [drafts, setDrafts] = useState<Record<string, DraftPoint>>({})
  const defaults = useMemo(
    () => layoutLevel(visible, positions, anchor),
    [visible, positions, anchor]
  )
  const points = useMemo(() => {
    const result = { ...defaults }
    for (const [id, draft] of Object.entries(drafts)) {
      if (Object.hasOwn(result, id) && draft.baseline === positions[id]) result[id] = draft.point
    }
    return result
  }, [defaults, positions, drafts])
  const preview = useCallback(
    (entityId: string, point: Point): void => {
      setDrafts((current) => ({ ...current, [entityId]: { point, baseline: positions[entityId] } }))
    },
    [positions]
  )
  // Preview changes never shift the coordinate origin or move neighboring cards during a drag.
  return { points, bounds: levelBounds(defaults, anchor), preview }
}

function hoveredEntity(event: WheelEvent, index: NavigationIndex): Entity | undefined {
  if (!(event.target instanceof Element)) return undefined
  const id = event.target.closest<HTMLElement>('[data-node-id]')?.dataset.nodeId
  return id ? index.entities.get(id) : undefined
}

function useWheelNavigation(
  ref: RefObject<HTMLElement | null>,
  index: NavigationIndex,
  parent: Entity | undefined,
  enter: (entity: Entity) => boolean,
  back: () => boolean
): void {
  const readyAt = useRef(0)
  useEffect(() => {
    const root = ref.current
    if (!root) return
    const navigate = (event: WheelEvent): (() => boolean) | null => {
      if (event.deltaY > 0) return parent ? back : null
      const entity = hoveredEntity(event, index)
      if (!entity || !index.children.get(entity.id)?.length) return null
      return () => enter(entity)
    }
    const wheel = (event: WheelEvent): void => {
      if (!(event.target instanceof Element) || event.target.closest(EDITABLE)) return
      if (event.ctrlKey || event.deltaY === 0) return
      const action = navigate(event)
      if (!action) return
      event.preventDefault()
      if (Date.now() < readyAt.current) return
      if (action()) readyAt.current = Date.now() + WHEEL_TRANSITION_MS
    }
    root.addEventListener('wheel', wheel, { passive: false })
    return () => root.removeEventListener('wheel', wheel)
  }, [ref, index, parent, enter, back])
}

function useViewportFocus(
  ref: RefObject<HTMLDivElement | null>,
  key: string,
  location: Location
): void {
  useLayoutEffect(() => {
    const viewport = ref.current
    if (!viewport) return
    const stage = viewport.firstElementChild
    if (!(stage instanceof HTMLElement)) return
    // The device rail reserves a right padding; centre in the content box, not under the rail.
    const railPad = parseFloat(getComputedStyle(viewport).paddingRight) || 0
    viewport.scrollLeft = Math.max(0, (stage.scrollWidth - viewport.clientWidth + railPad) / 2)
    viewport.scrollTop = Math.max(0, (stage.scrollHeight - viewport.clientHeight) / 2)
    const anchor = location.screenAnchor
    if (anchor) {
      // The viewport is the stage's positioned parent; offsets exclude its animated scale.
      const rect = viewport.getBoundingClientRect()
      const left = rect.left + viewport.clientLeft + stage.offsetLeft - viewport.scrollLeft
      const top = rect.top + viewport.clientTop + stage.offsetTop - viewport.scrollTop
      stage.style.setProperty('--graph-origin-x', `${anchor.x - left}px`)
      stage.style.setProperty('--graph-origin-y', `${anchor.y - top}px`)
    }
    const revealed = location.revealedId ? findCard(stage, location.revealedId) : undefined
    if (revealed) {
      // Offset geometry is stable while the stage's zoom transform is animating.
      viewport.scrollLeft = Math.max(
        0,
        stage.offsetLeft + revealed.offsetLeft + revealed.offsetWidth / 2 - viewport.clientWidth / 2
      )
      viewport.scrollTop = Math.max(
        0,
        stage.offsetTop + revealed.offsetTop + revealed.offsetHeight / 2 - viewport.clientHeight / 2
      )
    }
    ;(revealed ?? stage)
      .querySelector<HTMLButtonElement>('.graph-node-select')
      ?.focus({ preventScroll: true })
  }, [ref, key, location])
}

function findCard(root: HTMLElement | null, entityId: string): HTMLElement | undefined {
  return Array.from(root?.querySelectorAll<HTMLElement>('[data-node-id]') ?? []).find(
    (node) => node.dataset.nodeId === entityId
  )
}

function screenCenter(root: HTMLElement | null, entityId: string): Point | null {
  const rect = findCard(root, entityId)?.getBoundingClientRect()
  return rect && rect.width > 0
    ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }
    : null
}

function atLevel(parentId: string | null, page = 0): Location {
  return { parentId, page, origin: ORIGIN, screenAnchor: null, direction: 'out', revealedId: null }
}

export function useGraphNavigation(props: GraphNavigatorProps): NavigationModel {
  const { entities, relations, projectId, positions, onSelect } = props
  const index = useScopedIndex(entities, relations, projectId)
  const [location, setLocation] = useState<Location>(() => atLevel(null))
  const parent = index.entities.get(location.parentId ?? '')
  const level = childrenOf(index, parent?.id ?? null)
  const page = Math.min(location.page, Math.max(0, Math.ceil(level.length / MAX_VISIBLE_NODES) - 1))
  const visible = useMemo(
    () => level.slice(page * MAX_VISIBLE_NODES, (page + 1) * MAX_VISIBLE_NODES),
    [level, page]
  )
  const geometry = usePositions(visible, positions, location.origin)
  const links = useProjectedLinks(index, visible)
  const trail = parent ? [...index.pathTo(parent.id).map((step) => step.entity), parent] : []
  const rootRef = useRef<HTMLElement>(null)
  const viewportRef = useRef<HTMLDivElement>(null)
  const select = useCallback(
    (entity: Entity): void => onSelect(entity, index.pathTo(entity.id)),
    [index, onSelect]
  )
  const go = useCallback(
    (entity: Entity | null): void => {
      if (entity) onSelect(entity, index.pathTo(entity.id))
      // Up or across, a level packs around its parent's saved point, as entering it would.
      const origin = entity ? layoutLevel([entity], positions)[entity.id] : ORIGIN
      setLocation({ ...atLevel(entity?.id ?? null), origin })
    },
    [index, onSelect, positions]
  )
  const enter = useCallback(
    (entity: Entity): boolean => {
      if (!index.children.get(entity.id)?.length) return false
      onSelect(entity, index.pathTo(entity.id))
      setLocation({
        ...atLevel(entity.id),
        origin: geometry.points[entity.id] ?? ORIGIN,
        screenAnchor: screenCenter(rootRef.current, entity.id),
        direction: 'in'
      })
      return true
    },
    [index, geometry.points, onSelect]
  )
  const back = useCallback((): boolean => {
    if (!parent) return false
    const ancestor = index.entities.get(index.parent.get(parent.id)?.id ?? '')
    go(ancestor ?? null)
    return true
  }, [index, parent, go])
  const showLinked = (entity: Entity): void => {
    const ancestorId = index.parent.get(entity.id)?.id ?? null
    const ancestor = index.entities.get(ancestorId ?? '')
    const siblings = childrenOf(index, ancestorId)
    const targetPage = Math.floor(
      siblings.findIndex((candidate) => candidate.id === entity.id) / MAX_VISIBLE_NODES
    )
    // The revealed level packs around its parent's saved point, as entering it would.
    const origin = ancestor ? layoutLevel([ancestor], positions)[ancestor.id] : ORIGIN
    setLocation({ ...atLevel(ancestorId, Math.max(0, targetPage)), origin, revealedId: entity.id })
    onSelect(entity, index.pathTo(entity.id))
  }
  const key = `${parent?.id ?? 'root'}:${page}`
  useWheelNavigation(rootRef, index, parent, enter, back)
  useViewportFocus(viewportRef, key, location)
  return {
    index,
    parent,
    level,
    page,
    visible,
    ...geometry,
    links,
    trail,
    location,
    rootRef,
    viewportRef,
    key,
    select,
    enter,
    back,
    go,
    showLinked,
    setPage: (nextPage) => setLocation({ ...location, page: nextPage, revealedId: null })
  }
}

function useScopedIndex(
  entities: GraphNavigatorProps['entities'],
  relations: GraphNavigatorProps['relations'],
  projectId: string
): NavigationIndex {
  return useMemo(
    () =>
      buildNavigationIndex(
        entities.filter(
          (entity) => entity.project_id === undefined || entity.project_id === projectId
        ),
        relations
      ),
    [entities, relations, projectId]
  )
}

function useProjectedLinks(
  index: NavigationIndex,
  visible: readonly Entity[]
): readonly ProjectedLink[] {
  return useMemo(
    () =>
      projectCrossLinks(
        index,
        visible.map((entity) => entity.id)
      ),
    [index, visible]
  )
}
