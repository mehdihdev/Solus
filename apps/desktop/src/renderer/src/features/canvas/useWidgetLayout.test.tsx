// SOLUSDEV-235 / EXT-15 — load, optimistic edits, the 800 ms debounce, offline
// honesty, pruning, and the project switch. Fake timers + an injected client.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import type { WidgetLayoutApi, WidgetLayoutSlotApi } from '../../lib/api/resources.extensions'
import type { AvailableRefs } from './layout'
import { SAVE_DEBOUNCE_MS, useWidgetLayout, type WidgetLayoutDeps } from './useWidgetLayout'

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (error: unknown) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function serverLayout(layout: WidgetLayoutSlotApi[], updatedAt: string | null): WidgetLayoutApi {
  return { project_id: 'p1', layout, updated_at: updatedAt }
}

const SAVED: WidgetLayoutSlotApi[] = [
  { ref: 'builtin:livebench', size: 'wide' },
  { ref: 'ext:bom', size: 'standard' }
]

const ALL_KNOWN: AvailableRefs = {
  builtin: new Set(['livebench', 'reference']),
  ext: new Set(['bom'])
}

function fakeDeps(overrides: Partial<WidgetLayoutDeps> = {}): WidgetLayoutDeps & {
  load: ReturnType<typeof vi.fn>
  save: ReturnType<typeof vi.fn>
} {
  return {
    load: vi.fn(async () => serverLayout(SAVED, '2026-09-01T00:00:00Z')),
    save: vi.fn(async (_p: string, layout: readonly WidgetLayoutSlotApi[]) =>
      serverLayout([...layout], '2026-09-02T00:00:00Z')
    ),
    ...overrides
  } as WidgetLayoutDeps & { load: ReturnType<typeof vi.fn>; save: ReturnType<typeof vi.fn> }
}

const flush = (): Promise<void> => act(async () => {})
const tick = (ms: number): Promise<void> =>
  act(async () => {
    vi.advanceTimersByTime(ms)
  })

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('useWidgetLayout — load', () => {
  it('is loading until the GET resolves, then renders the saved layout', async () => {
    const gate = deferred<WidgetLayoutApi>()
    const deps = fakeDeps({ load: vi.fn(() => gate.promise) })
    const { result } = renderHook(() => useWidgetLayout('p1', ALL_KNOWN, deps))
    expect(result.current.status).toBe('loading')
    expect(result.current.layout).toEqual([])
    await act(async () => gate.resolve(serverLayout(SAVED, '2026-09-01T00:00:00Z')))
    expect(result.current.status).toBe('ready')
    expect(result.current.layout).toEqual(SAVED)
    expect(result.current.saveState).toBe('saved')
    expect(deps.load).toHaveBeenCalledWith('p1')
  })

  it('renders the default Live Bench slot for a never-arranged project and does not write it', async () => {
    const deps = fakeDeps({ load: vi.fn(async () => serverLayout([], null)) })
    const { result } = renderHook(() => useWidgetLayout('p1', ALL_KNOWN, deps))
    await flush()
    expect(result.current.layout).toEqual([{ ref: 'builtin:livebench', size: 'wide' }])
    await tick(SAVE_DEBOUNCE_MS * 3)
    expect(deps.save).not.toHaveBeenCalled()
  })

  it('an explicitly saved empty layout stays empty (not the default)', async () => {
    const deps = fakeDeps({ load: vi.fn(async () => serverLayout([], '2026-09-01T00:00:00Z')) })
    const { result } = renderHook(() => useWidgetLayout('p1', ALL_KNOWN, deps))
    await flush()
    expect(result.current.status).toBe('ready')
    expect(result.current.layout).toEqual([])
  })

  it('a failed GET is offline with the default layout, still editable locally', async () => {
    const deps = fakeDeps({
      load: vi.fn(async () => {
        throw new TypeError('network')
      })
    })
    const { result } = renderHook(() => useWidgetLayout('p1', ALL_KNOWN, deps))
    await flush()
    expect(result.current.status).toBe('offline')
    expect(result.current.saveState).toBe('offline')
    expect(result.current.layout).toEqual([{ ref: 'builtin:livebench', size: 'wide' }])
    act(() => result.current.add('ext:bom', 'standard'))
    expect(result.current.layout).toHaveLength(2)
  })

  it('ignores a GET that lands after the project changed', async () => {
    const first = deferred<WidgetLayoutApi>()
    const load = vi.fn((projectId: string) =>
      projectId === 'p1' ? first.promise : Promise.resolve(serverLayout([], null))
    )
    const deps = fakeDeps({ load })
    const { result, rerender } = renderHook(
      ({ projectId }: { projectId: string }) => useWidgetLayout(projectId, ALL_KNOWN, deps),
      { initialProps: { projectId: 'p1' } }
    )
    rerender({ projectId: 'p2' })
    await flush()
    expect(result.current.layout).toEqual([{ ref: 'builtin:livebench', size: 'wide' }])
    await act(async () => first.resolve(serverLayout(SAVED, '2026-09-01T00:00:00Z')))
    expect(result.current.layout).toEqual([{ ref: 'builtin:livebench', size: 'wide' }])
  })
})

describe('useWidgetLayout — optimistic edits and the debounced PUT', () => {
  it('applies each edit immediately and coalesces them into one PUT after 800 ms', async () => {
    const deps = fakeDeps()
    const { result } = renderHook(() => useWidgetLayout('p1', ALL_KNOWN, deps))
    await flush()
    act(() => result.current.resize('ext:bom', 'compact'))
    act(() => result.current.resize('ext:bom', 'full'))
    act(() => result.current.move('ext:bom', -1))
    expect(result.current.layout).toEqual([
      { ref: 'ext:bom', size: 'full' },
      { ref: 'builtin:livebench', size: 'wide' }
    ])
    expect(result.current.saveState).toBe('saving')
    await tick(SAVE_DEBOUNCE_MS - 1)
    expect(deps.save).not.toHaveBeenCalled()
    await tick(1)
    expect(deps.save).toHaveBeenCalledTimes(1)
    expect(deps.save).toHaveBeenCalledWith('p1', [
      { ref: 'ext:bom', size: 'full' },
      { ref: 'builtin:livebench', size: 'wide' }
    ])
    await flush()
    expect(result.current.saveState).toBe('saved')
  })

  it('an edit that changes nothing schedules no PUT', async () => {
    const deps = fakeDeps()
    const { result } = renderHook(() => useWidgetLayout('p1', ALL_KNOWN, deps))
    await flush()
    act(() => result.current.resize('ext:bom', 'standard'))
    act(() => result.current.remove('ext:nope'))
    act(() => result.current.add('ext:bom', 'full'))
    expect(result.current.saveState).toBe('saved')
    await tick(SAVE_DEBOUNCE_MS * 2)
    expect(deps.save).not.toHaveBeenCalled()
  })

  it('remove, add and restoreDefault all persist', async () => {
    const deps = fakeDeps()
    const { result } = renderHook(() => useWidgetLayout('p1', ALL_KNOWN, deps))
    await flush()
    act(() => result.current.remove('ext:bom'))
    act(() => result.current.remove('builtin:livebench'))
    expect(result.current.layout).toEqual([])
    act(() => result.current.add('builtin:reference', 'compact'))
    expect(result.current.layout).toEqual([{ ref: 'builtin:reference', size: 'compact' }])
    act(() => result.current.restoreDefault())
    expect(result.current.layout).toEqual([{ ref: 'builtin:livebench', size: 'wide' }])
    await tick(SAVE_DEBOUNCE_MS)
    expect(deps.save).toHaveBeenCalledTimes(1)
    expect(deps.save).toHaveBeenLastCalledWith('p1', [{ ref: 'builtin:livebench', size: 'wide' }])
  })

  it('a change during an in-flight PUT is written by a second PUT (last write wins)', async () => {
    const gate = deferred<WidgetLayoutApi>()
    let calls = 0
    const save = vi.fn(async (_p: string, layout: readonly WidgetLayoutSlotApi[]) => {
      calls += 1
      if (calls === 1) return gate.promise
      return serverLayout([...layout], 'later')
    })
    const deps = fakeDeps({ save })
    const { result } = renderHook(() => useWidgetLayout('p1', ALL_KNOWN, deps))
    await flush()
    act(() => result.current.resize('ext:bom', 'full'))
    await tick(SAVE_DEBOUNCE_MS)
    expect(save).toHaveBeenCalledTimes(1)
    act(() => result.current.resize('ext:bom', 'compact'))
    await act(async () => gate.resolve(serverLayout([], 'x')))
    expect(result.current.saveState).toBe('saving')
    await tick(SAVE_DEBOUNCE_MS)
    expect(save).toHaveBeenCalledTimes(2)
    expect(save).toHaveBeenLastCalledWith('p1', [
      { ref: 'builtin:livebench', size: 'wide' },
      { ref: 'ext:bom', size: 'compact' }
    ])
    await flush()
    expect(result.current.saveState).toBe('saved')
  })
})

describe('useWidgetLayout — offline', () => {
  it('a failed PUT keeps the local layout, reports offline, and the next edit retries', async () => {
    let fail = true
    const save = vi.fn(async (_p: string, layout: readonly WidgetLayoutSlotApi[]) => {
      if (fail) throw new TypeError('network')
      return serverLayout([...layout], 'x')
    })
    const deps = fakeDeps({ save })
    const { result } = renderHook(() => useWidgetLayout('p1', ALL_KNOWN, deps))
    await flush()
    act(() => result.current.resize('ext:bom', 'full'))
    await tick(SAVE_DEBOUNCE_MS)
    await flush()
    expect(result.current.saveState).toBe('offline')
    expect(result.current.layout[1]).toEqual({ ref: 'ext:bom', size: 'full' })
    // The note never clears on its own.
    await tick(SAVE_DEBOUNCE_MS * 5)
    expect(result.current.saveState).toBe('offline')
    fail = false
    act(() => result.current.resize('ext:bom', 'compact'))
    await tick(SAVE_DEBOUNCE_MS)
    await flush()
    expect(save).toHaveBeenCalledTimes(2)
    expect(result.current.saveState).toBe('saved')
  })

  it('retrySave re-sends the current layout without waiting for a change', async () => {
    let fail = true
    const save = vi.fn(async (_p: string, layout: readonly WidgetLayoutSlotApi[]) => {
      if (fail) throw new Error('500')
      return serverLayout([...layout], 'x')
    })
    const deps = fakeDeps({ save })
    const { result } = renderHook(() => useWidgetLayout('p1', ALL_KNOWN, deps))
    await flush()
    act(() => result.current.remove('ext:bom'))
    await tick(SAVE_DEBOUNCE_MS)
    await flush()
    expect(result.current.saveState).toBe('offline')
    fail = false
    act(() => result.current.retrySave())
    expect(result.current.saveState).toBe('saving')
    await flush()
    expect(save).toHaveBeenCalledTimes(2)
    expect(save).toHaveBeenLastCalledWith('p1', [{ ref: 'builtin:livebench', size: 'wide' }])
    expect(result.current.saveState).toBe('saved')
  })
})

describe('useWidgetLayout — pruning', () => {
  it('keeps everything while availability is unknown, then prunes and reports the count', async () => {
    const stored: WidgetLayoutSlotApi[] = [
      ...SAVED,
      { ref: 'builtin:gone', size: 'compact' },
      { ref: 'ext:uninstalled', size: 'wide' }
    ]
    const deps = fakeDeps({ load: vi.fn(async () => serverLayout(stored, 'x')) })
    const { result, rerender } = renderHook(
      ({ available }: { available: AvailableRefs | null }) =>
        useWidgetLayout('p1', available, deps),
      { initialProps: { available: null as AvailableRefs | null } }
    )
    await flush()
    expect(result.current.layout).toEqual(stored)
    expect(result.current.prunedCount).toBe(0)
    rerender({ available: { builtin: ALL_KNOWN.builtin, ext: null } })
    expect(result.current.prunedCount).toBe(1)
    expect(result.current.layout.map((s) => s.ref)).toEqual([
      'builtin:livebench',
      'ext:bom',
      'ext:uninstalled'
    ])
    rerender({ available: ALL_KNOWN })
    expect(result.current.prunedCount).toBe(2)
    expect(result.current.prunedRefs).toEqual(['builtin:gone', 'ext:uninstalled'])
    expect(result.current.layout).toEqual(SAVED)
  })

  it('pruning alone never writes; the next edit keeps pruned refs out of the PUT', async () => {
    const stored: WidgetLayoutSlotApi[] = [...SAVED, { ref: 'builtin:gone', size: 'compact' }]
    const deps = fakeDeps({ load: vi.fn(async () => serverLayout(stored, 'x')) })
    const { result } = renderHook(() => useWidgetLayout('p1', ALL_KNOWN, deps))
    await flush()
    await tick(SAVE_DEBOUNCE_MS * 2)
    expect(deps.save).not.toHaveBeenCalled()
    act(() => result.current.resize('ext:bom', 'full'))
    await tick(SAVE_DEBOUNCE_MS)
    expect(deps.save).toHaveBeenCalledWith('p1', [
      { ref: 'builtin:livebench', size: 'wide' },
      { ref: 'ext:bom', size: 'full' }
    ])
  })
})

describe('useWidgetLayout — project switch', () => {
  it('reloads for the new project and flushes a pending save for the old one', async () => {
    const deps = fakeDeps()
    const { result, rerender } = renderHook(
      ({ projectId }: { projectId: string }) => useWidgetLayout(projectId, ALL_KNOWN, deps),
      { initialProps: { projectId: 'p1' } }
    )
    await flush()
    act(() => result.current.resize('ext:bom', 'full'))
    rerender({ projectId: 'p2' })
    expect(deps.save).toHaveBeenCalledTimes(1)
    expect(deps.save).toHaveBeenCalledWith('p1', [
      { ref: 'builtin:livebench', size: 'wide' },
      { ref: 'ext:bom', size: 'full' }
    ])
    expect(result.current.status).toBe('loading')
    expect(deps.load).toHaveBeenLastCalledWith('p2')
    await flush()
    expect(result.current.status).toBe('ready')
    await tick(SAVE_DEBOUNCE_MS * 2)
    expect(deps.save).toHaveBeenCalledTimes(1)
  })
})
