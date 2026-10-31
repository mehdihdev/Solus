// SOLUSDEV-319: the pill's panel animates its height toward its content's
// natural height (CSS transition on an explicit height) instead of snapping.
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

describe('PillPanel', () => {
  it('opens from zero and follows its body height', () => {
    const ro = stubResizeObserver()
    render(<PillPanel>thread</PillPanel>)
    const panel = screen.getByRole('region', { name: 'SOL conversation' })
    expect(panel.style.height).toBe('0px')
    const body = panel.querySelector('.sol-pill-panel-body') as HTMLElement
    body.getBoundingClientRect = () => ({ height: 180.2 }) as DOMRect
    act(() => ro.fire())
    expect(panel.style.height).toBe('181px')
    expect(body).toHaveTextContent('thread')
  })

  it('without ResizeObserver it simply sizes to its content', () => {
    vi.stubGlobal('ResizeObserver', undefined)
    render(<PillPanel>thread</PillPanel>)
    expect(screen.getByRole('region', { name: 'SOL conversation' }).style.height).toBe('')
  })
})
