// The shared-focus engine (SOLUSDEV-191 / WS-01).
//
// One focused entity, broadcast to every mounted widget. Selecting a part in ANY widget re-scopes
// all of them — selection IS the query. This is the graph being *used* without anyone staring at
// a node-link canvas.
//
// The design constraint that shapes everything here is "focus changes must be cheap (no full
// reload)". Three things deliver that:
//
//   1. ONE fetch per selection, shared. Widgets read the store; they never fetch their own scope,
//      so mounting a tenth lens costs nothing.
//   2. A per-(entity, depth) cache. Cross-domain work is a back-and-forth — motor, driver, motor
//      again — so revisiting must be instant, and a cached focus never passes through `loading`
//      (no spinner, no unmount, just new props).
//   3. Zustand's own `subscribe` as the broadcast. No event bus: a second notification channel
//      is a second thing that can desynchronise.
//
// Not persisted — a focus is where you are right now, not a preference. Mirrors `shellStore`.
import { create } from 'zustand'
import type { FocusStep } from '@solus/shared-types'
import { getGraphNeighborhood, type Entity, type Neighborhood } from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { FocusStatus, WidgetFocus } from './widget.contract'

/** Mirrors the server's `MAX_DEPTH`; the route answers 422 beyond this. */
export const MAX_FOCUS_DEPTH = 2

export interface FocusState {
  focusedEntityId: string | null
  status: FocusStatus
  error: string | null
  depth: number
  path: readonly FocusStep[]
  /** Neighbourhoods already fetched, keyed by `${projectId}:${entityId}@${depth}`. */
  cache: Record<string, Neighborhood>
  /** In-flight cache keys, so a double-click does not become two uncapped traversals. */
  inFlight: Record<string, Promise<void>>

  focus: (entityId: string, path?: readonly FocusStep[]) => Promise<void>
  setDepth: (depth: number) => void
  clearProject: () => void
  reset: () => void
}

const INITIAL = {
  focusedEntityId: null as string | null,
  status: 'idle' as FocusStatus,
  error: null as string | null,
  depth: 1,
  path: [] as readonly FocusStep[],
  cache: {} as Record<string, Neighborhood>,
  inFlight: {} as Record<string, Promise<void>>
}

// Keyed by PROJECT as well as entity. `clearProject` is the primary defence, but entity ids are
// project-scoped and a cache that outlives a project switch — or a sign-out — would render one
// tenant's entity names, kinds and properties to the next user straight from renderer memory,
// with no request and no authorization check. Keying this way makes a missed reset a cache MISS
// rather than a cross-tenant read.
const cacheKey = (projectId: string, entityId: string, depth: number): string =>
  `${projectId}:${entityId}@${depth}`

const currentProjectId = (): string | undefined => useWorkspaceStore.getState().project?.id
let projectGeneration = 0

export const useFocusStore = create<FocusState>((set, get) => ({
  ...INITIAL,

  focus: async (entityId, path = INITIAL.path) => {
    const projectId = currentProjectId()
    // An entity id means nothing without a project scope, and guessing one would be a
    // cross-tenant read waiting to happen.
    if (!projectId) return
    if (path.some((step) => step.entity.projectId !== projectId)) {
      throw new Error('Focus path must stay in the current project')
    }
    const generation = projectGeneration

    const { depth, cache, inFlight } = get()
    const key = cacheKey(projectId, entityId, depth)

    if (cache[key]) {
      // The cheap path: no request, and deliberately no `loading` — widgets re-render, never
      // remount, so a back-and-forth across domains costs nothing.
      set({ focusedEntityId: entityId, path, status: 'ready', error: null })
      return
    }

    set({ focusedEntityId: entityId, path, status: 'loading', error: null })
    // Dedupe: dragging through a neighbour list would otherwise fire one bounded-but-real
    // traversal per click, and this endpoint is the expensive one.
    const pending: Promise<void> | undefined = inFlight[key]
    if (pending) return pending

    const request = loadFocus({ projectId, entityId, depth, generation })

    set((s) => ({ inFlight: { ...s.inFlight, [key]: request } }))
    return request
  },

  setDepth: (depth) => {
    if (!Number.isInteger(depth) || depth < 0 || depth > MAX_FOCUS_DEPTH) {
      throw new Error(`depth must be an integer between 0 and ${MAX_FOCUS_DEPTH}`)
    }
    if (depth === get().depth) return
    set({ depth })
    // Refetch, because the cache is keyed by depth: without this the selector finds nothing for
    // the new depth and the widgets render "0 entities" while `status` still says `ready` — an
    // empty graph presented as the whole truth.
    const focused = get().focusedEntityId
    if (focused) void get().focus(focused, get().path)
  },

  // Entity ids are project-scoped, so a project switch must drop the CACHE too — otherwise the
  // next project (or the next USER, after a sign-out) could render the previous one's entities
  // straight from memory, with no request and no authorization check.
  clearProject: () => {
    projectGeneration += 1
    set({ ...INITIAL, depth: get().depth })
  },

  reset: () => {
    projectGeneration += 1
    set({ ...INITIAL })
  }
}))

interface FocusRequest {
  projectId: string
  entityId: string
  depth: number
  generation: number
}

async function loadFocus({ projectId, entityId, depth, generation }: FocusRequest): Promise<void> {
  const { setState: set, getState: get } = useFocusStore
  const key = cacheKey(projectId, entityId, depth)
  const isCurrentProject = (): boolean =>
    generation === projectGeneration && currentProjectId() === projectId
  try {
    const neighborhood = await getGraphNeighborhood(projectId, entityId, { depth })
    if (!isCurrentProject()) return
    set((s) => ({
      cache: { ...s.cache, [key]: neighborhood },
      // Guarded: a fast second selection must not be overwritten by a slower earlier
      // response landing after it.
      status: s.focusedEntityId === entityId ? 'ready' : s.status,
      error: s.focusedEntityId === entityId ? null : s.error
    }))
  } catch (error: unknown) {
    // Guarded the same way. Without this, a slow rejection for A lands after a successful
    // focus on B and paints an error over B's perfectly good neighbourhood.
    // Deliberately NOT cached — a transient failure must not become a permanent empty view.
    if (!isCurrentProject() || get().focusedEntityId !== entityId) return
    set({
      status: 'error',
      error: error instanceof Error ? error.message : 'Could not load the neighbourhood'
    })
  } finally {
    if (isCurrentProject())
      set((s) => {
        const rest = { ...s.inFlight }
        delete rest[key]
        return { inFlight: rest }
      })
  }
}

/** The current neighbourhood, or null while it is still loading. */
export function selectNeighborhood(state: FocusState): Neighborhood | null {
  const projectId = currentProjectId()
  if (!state.focusedEntityId || !projectId) return null
  return state.cache[cacheKey(projectId, state.focusedEntityId, state.depth)] ?? null
}

/** The focused entity, read out of the neighbourhood rather than fetched a second time. */
export function selectFocusedEntity(state: FocusState): Entity | null {
  const neighborhood = selectNeighborhood(state)
  if (!neighborhood || !state.focusedEntityId) return null
  return neighborhood.entities.find((e) => e.id === state.focusedEntityId) ?? null
}

/**
 * Project the store into the widget contract. Widgets depend on THIS shape, never on the store,
 * so the focus engine's internals stay free to change without touching a single lens.
 */
export function widgetFocus(state: FocusState): WidgetFocus {
  return {
    status: state.status,
    focusedEntity: selectFocusedEntity(state),
    neighborhood: selectNeighborhood(state),
    error: state.error
  }
}
