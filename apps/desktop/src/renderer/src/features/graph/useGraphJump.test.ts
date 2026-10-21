import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useGraphJump } from './useGraphJump'
import { JUMP_TTL_MS, usePaletteStore } from '../palette/paletteStore'
import type { Entity } from '../../lib/api/resources'

const e = (id: string): Entity => ({ id, name: id, type: 'ic', domain: 'ee', source_key: null })

beforeEach(() => usePaletteStore.getState().reset())

describe('useGraphJump', () => {
  it('reveals a requested node of this project once and consumes the request', () => {
    const onReveal = vi.fn()
    renderHook(() => useGraphJump('p1', [e('e1')], onReveal))
    act(() => usePaletteStore.getState().requestJump('p1', 'e1'))
    expect(onReveal).toHaveBeenCalledExactlyOnceWith('e1')
    expect(usePaletteStore.getState().jump).toBeNull()
  })

  it('serves a request made before the Workspace mounted', () => {
    usePaletteStore.getState().requestJump('p1', 'e1')
    const onReveal = vi.fn()
    renderHook(() => useGraphJump('p1', [e('e1')], onReveal))
    expect(onReveal).toHaveBeenCalledWith('e1')
  })

  it('waits for the graph to load before revealing', () => {
    usePaletteStore.getState().requestJump('p1', 'e1')
    const onReveal = vi.fn()
    const { rerender } = renderHook(({ entities }) => useGraphJump('p1', entities, onReveal), {
      initialProps: { entities: null as Entity[] | null }
    })
    expect(onReveal).not.toHaveBeenCalled()
    expect(usePaletteStore.getState().jump).not.toBeNull()
    rerender({ entities: [e('e1')] })
    expect(onReveal).toHaveBeenCalledWith('e1')
  })

  it('drops a request for a node that is gone without revealing anything', () => {
    usePaletteStore.getState().requestJump('p1', 'gone')
    const onReveal = vi.fn()
    renderHook(() => useGraphJump('p1', [e('e1')], onReveal))
    expect(onReveal).not.toHaveBeenCalled()
    expect(usePaletteStore.getState().jump).toBeNull()
  })

  it('ignores a request for another project', () => {
    usePaletteStore.getState().requestJump('p2', 'e1')
    const onReveal = vi.fn()
    renderHook(() => useGraphJump('p1', [e('e1')], onReveal))
    expect(onReveal).not.toHaveBeenCalled()
  })
})

describe('useGraphJump — a jump never outlives the visit it was made for', () => {
  afterEach(() => vi.useRealTimers())

  it('drops a jump that waited past its expiry instead of selecting a node unprompted later', () => {
    vi.useFakeTimers()
    usePaletteStore.getState().requestJump('p1', 'e1')
    const onReveal = vi.fn()
    const { rerender } = renderHook(({ entities }) => useGraphJump('p1', entities, onReveal), {
      initialProps: { entities: null as Entity[] | null }
    })
    vi.advanceTimersByTime(JUMP_TTL_MS + 1)
    rerender({ entities: [e('e1')] })
    expect(onReveal).not.toHaveBeenCalled()
    expect(usePaletteStore.getState().jump).toBeNull()
  })
})
