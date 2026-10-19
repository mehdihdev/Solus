// SOLUSDEV-317 (Phase 4 M1): the default IntersectionObserver-backed seam that
// tells a command card its verbatim preview is on screen.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IN_VIEW_RATIO, observeInView } from './previewInView'

type Callback = (entries: Partial<IntersectionObserverEntry>[]) => void

afterEach(() => {
  vi.unstubAllGlobals()
})

function stubObserver(): {
  fire: Callback
  options: () => IntersectionObserverInit | undefined
  disconnect: ReturnType<typeof vi.fn>
} {
  let callback: Callback = () => undefined
  let init: IntersectionObserverInit | undefined
  const disconnect = vi.fn()
  vi.stubGlobal(
    'IntersectionObserver',
    vi.fn(function (this: unknown, cb: Callback, options?: IntersectionObserverInit) {
      callback = cb
      init = options
      return { observe: vi.fn(), disconnect }
    })
  )
  return { fire: (entries) => callback(entries), options: () => init, disconnect }
}

describe('observeInView', () => {
  it('reports in view only at or above half visible', () => {
    const io = stubObserver()
    const onChange = vi.fn()
    const stop = observeInView(document.createElement('div'), onChange)
    io.fire([{ isIntersecting: true, intersectionRatio: 0.2 }])
    io.fire([{ isIntersecting: true, intersectionRatio: IN_VIEW_RATIO }])
    io.fire([{ isIntersecting: false, intersectionRatio: 0 }])
    expect(onChange.mock.calls).toEqual([[false], [true], [false]])
    expect(io.options()?.threshold).toEqual([0, IN_VIEW_RATIO])
    stop()
    expect(io.disconnect).toHaveBeenCalled()
  })

  it('never reports in view without IntersectionObserver (fails closed)', () => {
    vi.stubGlobal('IntersectionObserver', undefined)
    const onChange = vi.fn()
    const stop = observeInView(document.createElement('div'), onChange)
    stop()
    expect(onChange).not.toHaveBeenCalled()
  })
})
