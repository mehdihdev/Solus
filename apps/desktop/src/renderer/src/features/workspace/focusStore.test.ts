// The shared-focus engine (SOLUSDEV-191 / WS-01).
//
// The acceptance criterion that carries real risk is "focus changes are cheap (no full reload)",
// so the fetch-counting tests below are the load-bearing ones: selecting a part must cost ONE
// request no matter how many widgets are mounted, and returning to a part already visited must
// cost zero.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useFocusStore, widgetFocus } from './focusStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getGraphNeighborhood: vi.fn() }
})

const ROOT: resources.Entity = {
  id: 'e-root',
  type: 'motor',
  domain: 'electrical',
  name: 'knee_motor',
  source_key: ':motor'
}
const NEIGHBOUR: resources.Entity = {
  id: 'e-nb',
  type: 'ic',
  domain: 'electrical',
  name: 'U4',
  source_key: ':u4'
}

function neighborhood(root: resources.Entity, ...rest: resources.Entity[]): resources.Neighborhood {
  return {
    entities: [root, ...rest],
    edges: rest.map((e, i) => ({
      id: `edge-${i}`,
      type: 'drives',
      from_entity_id: root.id,
      to_entity_id: e.id
    })),
    truncated: false
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  useFocusStore.getState().reset()
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Strider' } })
  vi.mocked(resources.getGraphNeighborhood).mockResolvedValue(neighborhood(ROOT, NEIGHBOUR))
})

describe('initial state', () => {
  it('is idle with nothing focused', () => {
    const s = useFocusStore.getState()
    expect(s.status).toBe('idle')
    expect(s.focusedEntityId).toBeNull()
    expect(widgetFocus(s).focusedEntity).toBeNull()
  })
})

describe('focusing an entity', () => {
  it('fetches the neighbourhood once and exposes it', async () => {
    await useFocusStore.getState().focus('e-root')
    const focus = widgetFocus(useFocusStore.getState())

    expect(focus.status).toBe('ready')
    expect(focus.focusedEntity?.name).toBe('knee_motor')
    expect(focus.neighborhood?.entities).toHaveLength(2)
    expect(resources.getGraphNeighborhood).toHaveBeenCalledTimes(1)
    expect(resources.getGraphNeighborhood).toHaveBeenCalledWith('p1', 'e-root', { depth: 1 })
  })

  it('resolves focusedEntity from the neighbourhood rather than a second request', async () => {
    await useFocusStore.getState().focus('e-root')
    expect(resources.getGraphNeighborhood).toHaveBeenCalledTimes(1)
  })
})

describe('focus changes are cheap', () => {
  it('re-focusing the SAME entity does not refetch', async () => {
    await useFocusStore.getState().focus('e-root')
    await useFocusStore.getState().focus('e-root')
    expect(resources.getGraphNeighborhood).toHaveBeenCalledTimes(1)
  })

  it('returning to an already-visited entity is served from cache', async () => {
    vi.mocked(resources.getGraphNeighborhood).mockResolvedValueOnce(neighborhood(ROOT, NEIGHBOUR))
    vi.mocked(resources.getGraphNeighborhood).mockResolvedValueOnce(neighborhood(NEIGHBOUR, ROOT))

    await useFocusStore.getState().focus('e-root')
    await useFocusStore.getState().focus('e-nb')
    expect(resources.getGraphNeighborhood).toHaveBeenCalledTimes(2)

    await useFocusStore.getState().focus('e-root') // back again — no third request
    expect(resources.getGraphNeighborhood).toHaveBeenCalledTimes(2)
    expect(widgetFocus(useFocusStore.getState()).focusedEntity?.name).toBe('knee_motor')
  })

  it('serves a cached focus without passing through a loading state', async () => {
    // What "no full reload" means to a widget: no spinner, no unmount, just new props.
    await useFocusStore.getState().focus('e-root')
    await useFocusStore.getState().focus('e-nb')

    const seen: string[] = []
    const unsubscribe = useFocusStore.subscribe((s) => seen.push(s.status))
    await useFocusStore.getState().focus('e-root')
    unsubscribe()

    expect(seen).not.toContain('loading')
    expect(seen).toContain('ready')
  })
})

describe('broadcast', () => {
  it('notifies every subscriber on a focus change — this is what re-scopes the widgets', async () => {
    const widgetA = vi.fn()
    const widgetB = vi.fn()
    const unsubA = useFocusStore.subscribe(widgetA)
    const unsubB = useFocusStore.subscribe(widgetB)

    await useFocusStore.getState().focus('e-root')

    expect(widgetA).toHaveBeenCalled()
    expect(widgetB).toHaveBeenCalled()
    unsubA()
    unsubB()
  })
})

describe('failure and scope changes', () => {
  it('reports an error without leaving a half-applied focus', async () => {
    vi.mocked(resources.getGraphNeighborhood).mockRejectedValueOnce(new Error('unreachable'))
    await useFocusStore.getState().focus('e-root')

    const focus = widgetFocus(useFocusStore.getState())
    expect(focus.status).toBe('error')
    expect(focus.error).toBeTruthy()
    expect(focus.neighborhood).toBeNull()
  })

  it('does not cache a failed fetch', async () => {
    vi.mocked(resources.getGraphNeighborhood).mockRejectedValueOnce(new Error('unreachable'))
    await useFocusStore.getState().focus('e-root')
    await useFocusStore.getState().focus('e-root')
    expect(resources.getGraphNeighborhood).toHaveBeenCalledTimes(2)
  })

  it('a late failure for an abandoned entity does not clobber the current focus', async () => {
    // Regression: the success path guarded against stale responses but the failure path did not,
    // so a slow rejection for A landed after a successful focus on B and painted an error banner
    // over B's perfectly good neighbourhood.
    let rejectA: (reason: Error) => void = () => {}
    vi.mocked(resources.getGraphNeighborhood).mockImplementationOnce(
      () => new Promise((_resolve, reject) => (rejectA = reject))
    )
    vi.mocked(resources.getGraphNeighborhood).mockResolvedValueOnce(neighborhood(NEIGHBOUR, ROOT))

    const slowA = useFocusStore.getState().focus('e-root') // never resolves yet
    await useFocusStore.getState().focus('e-nb') // user moves on; this one succeeds
    expect(useFocusStore.getState().status).toBe('ready')

    rejectA(new Error('unreachable'))
    await slowA

    const focus = widgetFocus(useFocusStore.getState())
    expect(focus.status).toBe('ready')
    expect(focus.error).toBeNull()
    expect(focus.focusedEntity?.name).toBe('U4')
  })

  it('is a no-op with no project selected — entity ids are meaningless without scope', async () => {
    useWorkspaceStore.setState({ linked: true, project: null })
    await useFocusStore.getState().focus('e-root')
    expect(resources.getGraphNeighborhood).not.toHaveBeenCalled()
    expect(useFocusStore.getState().status).toBe('idle')
  })

  it('clearProject drops the focus AND the cache, so another project cannot read stale entities', async () => {
    await useFocusStore.getState().focus('e-root')
    useFocusStore.getState().clearProject()

    expect(useFocusStore.getState().focusedEntityId).toBeNull()
    await useFocusStore.getState().focus('e-root')
    expect(resources.getGraphNeighborhood).toHaveBeenCalledTimes(2) // refetched, not cached
  })
})

describe('project scope is a cache boundary, not just a fetch parameter', () => {
  it('does not serve one project cached neighbourhood to another', async () => {
    // Security: entity ids are project-scoped. A cache that outlives the switch would render
    // project A's entity names and properties under project B with no request at all.
    await useFocusStore.getState().focus('e-root')
    expect(resources.getGraphNeighborhood).toHaveBeenCalledTimes(1)

    useWorkspaceStore.setState({ linked: true, project: { id: 'p2', name: 'Other' } })
    await useFocusStore.getState().focus('e-root')

    expect(resources.getGraphNeighborhood).toHaveBeenCalledTimes(2)
    expect(resources.getGraphNeighborhood).toHaveBeenLastCalledWith('p2', 'e-root', { depth: 1 })
  })

  it('renders nothing from cache once the project changes, even before a refetch', async () => {
    await useFocusStore.getState().focus('e-root')
    useWorkspaceStore.setState({ linked: true, project: { id: 'p2', name: 'Other' } })
    expect(widgetFocus(useFocusStore.getState()).neighborhood).toBeNull()
  })

  it('reset drops the cache — sign-out must not leave a tenant readable in memory', async () => {
    await useFocusStore.getState().focus('e-root')
    useFocusStore.getState().reset()
    expect(useFocusStore.getState().cache).toEqual({})
    expect(useFocusStore.getState().focusedEntityId).toBeNull()
  })
})

describe('request amplification', () => {
  it('dedupes concurrent focuses of the same entity into one request', async () => {
    const store = useFocusStore.getState()
    await Promise.all([store.focus('e-root'), store.focus('e-root'), store.focus('e-root')])
    expect(resources.getGraphNeighborhood).toHaveBeenCalledTimes(1)
  })
})

describe('depth', () => {
  it('re-fetches on its own when the depth changes, and caches per depth', async () => {
    // setDepth must refetch rather than wait to be asked: the cache is keyed by depth, so without
    // it the selector finds nothing and the widgets show "0 entities" while status says `ready` —
    // an empty graph presented as the whole truth.
    await useFocusStore.getState().focus('e-root')
    useFocusStore.getState().setDepth(2)
    await Promise.resolve()
    await useFocusStore.getState().focus('e-root')
    expect(resources.getGraphNeighborhood).toHaveBeenCalledTimes(2)
    expect(resources.getGraphNeighborhood).toHaveBeenLastCalledWith('p1', 'e-root', { depth: 2 })

    useFocusStore.getState().setDepth(1)
    await useFocusStore.getState().focus('e-root') // depth 1 is still cached
    expect(resources.getGraphNeighborhood).toHaveBeenCalledTimes(2)
  })

  it('never leaves an empty neighbourhood looking like a ready answer', async () => {
    await useFocusStore.getState().focus('e-root')
    useFocusStore.getState().setDepth(2)
    const focus = widgetFocus(useFocusStore.getState())
    expect(focus.neighborhood === null ? focus.status : 'ready').not.toBe('ready')
  })

  it('rejects a depth the server would refuse', () => {
    expect(() => useFocusStore.getState().setDepth(5)).toThrow()
  })
})
