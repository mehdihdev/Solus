// SOLUSDEV-319: the pill's panel springs its height toward its content's
// natural height, frame by frame, instead of snapping or restarting an ease.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { PillPanel } from './PillPanel'

afterEach(() => void vi.unstubAllGlobals())

function stubResizeObserver(): { fire: () => void } {
  const callbacks: ResizeObserverCallback[] = []
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(cb: ResizeObserverCallback) {
        callbacks.push(cb)
      }
      observe = vi.fn()
      disconnect = vi.fn()
    }
  )
  return { fire: () => callbacks.forEach((cb) => cb([], {} as ResizeObserver)) }
}

/** A manual frame clock: `frames(n)` runs n 60 Hz frames. */
function stubFrames(): { frames: (n: number) => void; pending: () => number } {
  let queue: FrameRequestCallback[] = []
  let now = 0
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    queue.push(cb)
    return queue.length
  })
  vi.stubGlobal('cancelAnimationFrame', () => {
    queue = []
  })
  return {
    frames: (n) => {
      for (let i = 0; i < n; i += 1) {
        now += 1000 / 60
        const run = queue
        queue = []
        run.forEach((cb) => cb(now))
      }
    },
    pending: () => queue.length
  }
}

function stubReducedMotion(reduce: boolean): void {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: reduce && query.includes('reduce'),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn()
  }))
}

function mount(): { panel: HTMLElement; setBody: (h: number) => void } {
  render(<PillPanel>thread</PillPanel>)
  const panel = screen.getByRole('region', { name: 'SOL conversation' })
  const body = panel.querySelector('.sol-pill-panel-body') as HTMLElement
  return { panel, setBody: (h) => (body.getBoundingClientRect = () => ({ height: h }) as DOMRect) }
}

const px = (el: HTMLElement): number => parseFloat(el.style.height)

describe('PillPanel', () => {
  it('opens from zero and springs to its body height', () => {
    stubReducedMotion(false)
    const ro = stubResizeObserver()
    const clock = stubFrames()
    const { panel, setBody } = mount()
    expect(panel.style.height).toBe('0px')
    setBody(180.2)
    act(() => ro.fire())
    clock.frames(4)
    expect(px(panel)).toBeGreaterThan(0)
    expect(px(panel)).toBeLessThan(181)
    clock.frames(40)
    expect(panel.style.height).toBe('181px')
    expect(clock.pending()).toBe(0)
    expect(panel).toHaveTextContent('thread')
  })

  it('keeps moving smoothly when the target grows mid-flight (streaming)', () => {
    stubReducedMotion(false)
    const ro = stubResizeObserver()
    const clock = stubFrames()
    const { panel, setBody } = mount()
    setBody(100)
    act(() => ro.fire())
    clock.frames(5)
    const mid = px(panel)
    setBody(160)
    act(() => ro.fire())
    clock.frames(1)
    expect(px(panel)).toBeGreaterThan(mid)
    clock.frames(40)
    expect(panel.style.height).toBe('160px')
  })

  it('shrinks back down the same way', () => {
    stubReducedMotion(false)
    const ro = stubResizeObserver()
    const clock = stubFrames()
    const { panel, setBody } = mount()
    setBody(200)
    act(() => ro.fire())
    clock.frames(40)
    setBody(80)
    act(() => ro.fire())
    clock.frames(3)
    expect(px(panel)).toBeLessThan(200)
    expect(px(panel)).toBeGreaterThan(80)
    clock.frames(40)
    expect(panel.style.height).toBe('80px')
  })

  it('an unchanged height schedules no frame (idle stays frame-free)', () => {
    stubReducedMotion(false)
    const ro = stubResizeObserver()
    const clock = stubFrames()
    const { setBody } = mount()
    setBody(0)
    act(() => ro.fire())
    expect(clock.pending()).toBe(0)
  })

  it('jumps straight to the height under reduced motion', () => {
    stubReducedMotion(true)
    const ro = stubResizeObserver()
    const clock = stubFrames()
    const { panel, setBody } = mount()
    setBody(180.2)
    act(() => ro.fire())
    expect(panel.style.height).toBe('181px')
    expect(clock.pending()).toBe(0)
  })

  it('without ResizeObserver it simply sizes to its content', () => {
    vi.stubGlobal('ResizeObserver', undefined)
    render(<PillPanel>thread</PillPanel>)
    expect(screen.getByRole('region', { name: 'SOL conversation' }).style.height).toBe('')
  })
})
