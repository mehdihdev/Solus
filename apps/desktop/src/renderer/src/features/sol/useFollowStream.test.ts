// SOLUSDEV-326: the thread follows a streaming reply until the person scrolls up themselves.
import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useFollowStream } from './useFollowStream'

/** A list element whose scroll geometry the test controls. */
function fakeList(
  scrollHeight: number,
  clientHeight = 600
): { el: HTMLDivElement; pins: number[] } {
  const el = document.createElement('div')
  const pins: number[] = []
  let top = 0
  Object.defineProperty(el, 'scrollHeight', { configurable: true, get: () => scrollHeight })
  Object.defineProperty(el, 'clientHeight', { configurable: true, get: () => clientHeight })
  Object.defineProperty(el, 'scrollTop', {
    configurable: true,
    get: () => top,
    set: (v: number) => {
      top = v
      pins.push(v)
    }
  })
  return { el, pins }
}

const wheel = (deltaY: number): React.WheelEvent => ({ deltaY }) as React.WheelEvent
const key = (k: string): React.KeyboardEvent => ({ key: k }) as React.KeyboardEvent

describe('useFollowStream', () => {
  it('pins to the bottom as the reply grows', () => {
    const { el, pins } = fakeList(2_000)
    const { rerender } = renderHook(({ g }) => useFollowStream({ current: el }, 2, g), {
      initialProps: { g: 1 }
    })
    rerender({ g: 2 })
    expect(pins.length).toBe(2)
  })

  it('stops after a wheel up, and a new row re-engages it', () => {
    const { el, pins } = fakeList(2_000)
    const { result, rerender } = renderHook(
      ({ rows, g }) => useFollowStream({ current: el }, rows, g),
      { initialProps: { rows: 2, g: 1 } }
    )
    result.current.onWheel(wheel(-120))
    rerender({ rows: 2, g: 2 })
    expect(pins.length).toBe(1)
    rerender({ rows: 3, g: 0 })
    expect(pins.length).toBe(2)
  })

  it('stops on PageUp, not on PageDown', () => {
    const { el, pins } = fakeList(2_000)
    const { result, rerender } = renderHook(({ g }) => useFollowStream({ current: el }, 2, g), {
      initialProps: { g: 1 }
    })
    result.current.onKeyDown(key('PageDown'))
    rerender({ g: 2 })
    expect(pins.length).toBe(2)
    result.current.onKeyDown(key('PageUp'))
    rerender({ g: 3 })
    expect(pins.length).toBe(2)
  })

  it('keeps following when the browser moves the list by itself', () => {
    const { el, pins } = fakeList(2_000)
    const { result, rerender } = renderHook(({ g }) => useFollowStream({ current: el }, 2, g), {
      initialProps: { g: 1 }
    })
    el.scrollTop = 400 // a clamp after rows above re-measured — no input from the person
    result.current.onScroll()
    rerender({ g: 2 })
    expect(pins.at(-1)).toBe(2_000)
  })

  it('stops while the person drags the scrollbar up, and resumes at the bottom', () => {
    const { el, pins } = fakeList(2_000)
    const { result, rerender } = renderHook(({ g }) => useFollowStream({ current: el }, 2, g), {
      initialProps: { g: 1 }
    })
    result.current.onPointerDown()
    el.scrollTop = 500
    result.current.onScroll()
    window.dispatchEvent(new Event('pointerup'))
    rerender({ g: 2 })
    expect(pins.at(-1)).toBe(500)
    el.scrollTop = 1_400
    result.current.onScroll()
    rerender({ g: 3 })
    expect(pins.at(-1)).toBe(2_000)
  })

  it('re-pins when a row changes height while following', () => {
    const callbacks: Array<() => void> = []
    const original = globalThis.ResizeObserver
    globalThis.ResizeObserver = class {
      constructor(cb: () => void) {
        callbacks.push(cb)
      }
      observe(): void {}
      disconnect(): void {}
      unobserve(): void {}
    } as unknown as typeof ResizeObserver
    try {
      const { el, pins } = fakeList(2_000)
      el.appendChild(document.createElement('div'))
      renderHook(() => useFollowStream({ current: el }, 2, 1))
      const before = pins.length
      callbacks.forEach((cb) => cb())
      expect(pins.length).toBe(before + 1)
    } finally {
      globalThis.ResizeObserver = original
    }
  })
})
