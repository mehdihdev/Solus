import { describe, it, expect, afterEach, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useActiveSection } from './useActiveSection'

type Callback = (entries: Partial<IntersectionObserverEntry>[]) => void

function installObserver(): { fire: Callback; observed: Element[] } {
  const state = { fire: (() => undefined) as Callback, observed: [] as Element[] }
  class FakeObserver {
    constructor(cb: Callback) {
      state.fire = cb
    }
    observe(el: Element): void {
      state.observed.push(el)
    }
    disconnect(): void {
      state.observed = []
    }
  }
  vi.stubGlobal('IntersectionObserver', FakeObserver)
  return state
}

function section(id: string): HTMLElement {
  const el = document.createElement('section')
  el.id = id
  document.body.appendChild(el)
  return el
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.replaceChildren()
})

describe('useActiveSection', () => {
  it('is null without IntersectionObserver (jsdom, old runtimes)', () => {
    vi.stubGlobal('IntersectionObserver', undefined)
    const { result } = renderHook(() => useActiveSection(['settings-sol']))
    expect(result.current).toBeNull()
  })

  it('follows the topmost section in view', () => {
    const io = installObserver()
    const sol = section('settings-sol')
    const appearance = section('settings-appearance')
    const { result } = renderHook(() => useActiveSection(['settings-sol', 'settings-appearance']))
    expect(io.observed).toEqual([sol, appearance])
    act(() =>
      io.fire([
        { target: appearance, isIntersecting: true },
        { target: sol, isIntersecting: true }
      ])
    )
    expect(result.current).toBe('settings-sol')
    act(() => io.fire([{ target: sol, isIntersecting: false }]))
    expect(result.current).toBe('settings-appearance')
  })
})
