import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Entity } from '../../lib/api/resources'
import { OPTIMISTIC_MAX_AGE_MS, useOptimisticGraph } from './useOptimisticGraph'

const robot: Entity = {
  id: 'arm',
  type: 'physical_robot',
  domain: 'project',
  name: 'Bench arm',
  source_key: null
}
const other: Entity = { ...robot, id: 'e1', name: 'elbow motor' }

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('useOptimisticGraph', () => {
  it('shows an added entity verbatim until the authoritative snapshot carries its id', () => {
    const view = renderHook(({ snapshot }) => useOptimisticGraph(snapshot), {
      initialProps: { snapshot: [other] as readonly Entity[] | null }
    })
    expect(view.result.current.entities).toEqual([])
    act(() => view.result.current.add(robot))
    expect(view.result.current.entities).toEqual([robot])
    expect(view.result.current.entities[0]).toBe(robot)
    // An unrelated refetch keeps it; the one that carries the id prunes it.
    view.rerender({ snapshot: [other] })
    expect(view.result.current.entities).toEqual([robot])
    view.rerender({ snapshot: [other, { ...robot, name: 'renamed' }] })
    expect(view.result.current.entities).toEqual([])
  })

  it('prunes by max-age when the snapshot never arrives', () => {
    const view = renderHook(() => useOptimisticGraph(null))
    act(() => view.result.current.add(robot))
    act(() => vi.advanceTimersByTime(OPTIMISTIC_MAX_AGE_MS - 1))
    expect(view.result.current.entities).toEqual([robot])
    act(() => vi.advanceTimersByTime(1))
    expect(view.result.current.entities).toEqual([])
  })

  it('keeps one entry per id and a stable list identity between renders', () => {
    const view = renderHook(() => useOptimisticGraph([]))
    act(() => view.result.current.add(robot))
    act(() => view.result.current.add({ ...robot, name: 'Bench arm (again)' }))
    expect(view.result.current.entities).toHaveLength(1)
    const before = view.result.current.entities
    view.rerender()
    expect(view.result.current.entities).toBe(before)
  })
})
