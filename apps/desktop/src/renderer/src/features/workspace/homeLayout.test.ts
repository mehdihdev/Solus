// SOLUSDEV-328 — Home's team overview picks its columns from its own width (docs/wireflows/home.md
// "Fills the window"), never the window's: opening the SOL sidebar reflows it like a resize.
import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  HOME_SPLIT_MIN,
  HOME_WIDE_MIN,
  PROJECT_FULL_MIN,
  PROJECT_LIST_MIN,
  homeLayoutFor,
  projectPageLayoutFor,
  useHomeLayout
} from './homeLayout'

describe('homeLayoutFor', () => {
  it('stacks below the split width, splits in between, and goes wide from 1680px', () => {
    expect(homeLayoutFor(HOME_SPLIT_MIN - 1)).toBe('stack')
    expect(homeLayoutFor(HOME_SPLIT_MIN)).toBe('split')
    expect(homeLayoutFor(HOME_WIDE_MIN - 1)).toBe('split')
    expect(homeLayoutFor(HOME_WIDE_MIN)).toBe('wide')
  })

  it('treats an unmeasured width as split, so nothing is hidden before the first measure', () => {
    expect(homeLayoutFor(0)).toBe('split')
    expect(homeLayoutFor(Number.NaN)).toBe('split')
  })
})

describe('projectPageLayoutFor (SOLUSDEV-328, design P2)', () => {
  it('switches projects from the header when narrow, lists them beside the project, adds activity when full', () => {
    expect(projectPageLayoutFor(PROJECT_LIST_MIN - 1)).toBe('narrow')
    expect(projectPageLayoutFor(PROJECT_LIST_MIN)).toBe('list')
    expect(projectPageLayoutFor(PROJECT_FULL_MIN - 1)).toBe('list')
    expect(projectPageLayoutFor(PROJECT_FULL_MIN)).toBe('full')
  })

  it('treats an unmeasured width as list', () => {
    expect(projectPageLayoutFor(0)).toBe('list')
  })
})

describe('useHomeLayout', () => {
  const original = globalThis.ResizeObserver
  afterEach(() => {
    globalThis.ResizeObserver = original
  })

  it('is split where the platform cannot measure', () => {
    // @ts-expect-error — jsdom has no ResizeObserver; make sure of it.
    delete globalThis.ResizeObserver
    const ref = { current: document.createElement('div') }
    const { result } = renderHook(() => useHomeLayout(ref))
    expect(result.current).toBe('split')
  })

  it('follows the element as it is resized, and stops observing on unmount', () => {
    let notify: ((entries: Array<{ contentRect: { width: number } }>) => void) | null = null
    const disconnect = vi.fn()
    globalThis.ResizeObserver = class {
      constructor(cb: (entries: Array<{ contentRect: { width: number } }>) => void) {
        notify = cb
      }
      observe(): void {}
      unobserve(): void {}
      disconnect = disconnect
    } as unknown as typeof ResizeObserver
    const el = document.createElement('div')
    el.getBoundingClientRect = () => ({ width: 1800 }) as DOMRect
    const ref = { current: el }
    const { result, unmount } = renderHook(() => useHomeLayout(ref))
    // Measured before the observer's first report: no split frame first.
    expect(result.current).toBe('wide')
    act(() => notify?.([{ contentRect: { width: 1200 } }]))
    expect(result.current).toBe('split')
    act(() => notify?.([{ contentRect: { width: 1744 } }]))
    expect(result.current).toBe('wide')
    act(() => notify?.([{ contentRect: { width: 700 } }]))
    expect(result.current).toBe('stack')
    unmount()
    expect(disconnect).toHaveBeenCalled()
  })
})
