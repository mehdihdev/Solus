// SOLUSDEV-327 — sidebar presence phases, window fit and resize.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useSidebarPresence, useSidebarResize, useWindowFit } from './sidebarHooks'
import { SIDEBAR_DEFAULT_WIDTH, useSolSidebarStore } from './solSidebarStore'
import { motionMs } from './sidebarMotion.constants'

beforeEach(() => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 })
})

describe('useSidebarPresence', () => {
  it('enters then settles open, and leaves then unmounts', async () => {
    const { result, rerender } = renderHook(({ open }) => useSidebarPresence(open, 'home'), {
      initialProps: { open: false }
    })
    expect(result.current.phase).toBe('closed')
    rerender({ open: true })
    expect(['entering', 'open']).toContain(result.current.phase)
    await waitFor(() => expect(result.current.phase).toBe('open'))
    rerender({ open: false })
    expect(['leaving', 'closed']).toContain(result.current.phase)
    await waitFor(() => expect(result.current.phase).toBe('closed'))
  })

  it('snaps to the new screen without motion', () => {
    const { result, rerender } = renderHook(({ open, key }) => useSidebarPresence(open, key), {
      initialProps: { open: false, key: 'home' }
    })
    rerender({ open: true, key: 'bench' })
    expect(result.current.phase).toBe('open')
  })

  it('plays an exit phase, then runs its continuation', async () => {
    const { result, rerender } = renderHook(({ open }) => useSidebarPresence(open, 'home'), {
      initialProps: { open: true }
    })
    // The continuation closes the store, as the host's expand and pop-out do.
    const done = vi.fn(() => rerender({ open: false }))
    act(() => result.current.exit('expanding', 420, done))
    expect(result.current.phase).toBe('expanding')
    await waitFor(() => expect(done).toHaveBeenCalled())
    expect(result.current.phase).toBe('closed')
  })
})

describe('useSidebarPresence — screen change mid-exit', () => {
  it('drops the continuation when the screen changed during the motion', async () => {
    const done = vi.fn()
    const { result, rerender } = renderHook(({ key }) => useSidebarPresence(true, key), {
      initialProps: { key: 'home' }
    })
    act(() => result.current.exit('expanding', 420, done))
    rerender({ key: 'bench' })
    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(done).not.toHaveBeenCalled()
  })
})

describe('useSidebarResize', () => {
  it('cleans up a drag cut short by unmount or pointer cancel', () => {
    useSolSidebarStore.getState().reset()
    const { result, unmount } = renderHook(() => useSidebarResize())
    const down = {
      clientX: 1000,
      preventDefault: vi.fn()
    } as unknown as React.PointerEvent<HTMLElement>
    act(() => result.current.onPointerDown(down))
    expect(document.body).toHaveClass('sol-sb-resizing')
    window.dispatchEvent(new Event('pointercancel'))
    expect(document.body).not.toHaveClass('sol-sb-resizing')
    act(() => result.current.onPointerDown(down))
    unmount()
    expect(document.body).not.toHaveClass('sol-sb-resizing')
    const move = new MouseEvent('pointermove', { clientX: 900 })
    window.dispatchEvent(move)
    expect(useSolSidebarStore.getState().width).toBe(SIDEBAR_DEFAULT_WIDTH)
  })
})

describe('useSidebarResize — width that scales until dragged (SOLUSDEV-328)', () => {
  const setWindow = (width: number): void => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
    window.dispatchEvent(new Event('resize'))
  }

  it('follows the window while the person has not sized it', () => {
    useSolSidebarStore.getState().reset()
    setWindow(1920)
    const { result } = renderHook(() => useSidebarResize())
    expect(result.current.width).toBe(422)
    act(() => setWindow(2560))
    expect(result.current.width).toBe(480)
  })

  it('keeps a dragged width once set, whatever the window does', () => {
    useSolSidebarStore.getState().reset()
    setWindow(2560)
    const { result } = renderHook(() => useSidebarResize())
    const down = {
      clientX: 1000,
      preventDefault: vi.fn()
    } as unknown as React.PointerEvent<HTMLElement>
    act(() => result.current.onPointerDown(down))
    act(() => {
      window.dispatchEvent(new MouseEvent('pointermove', { clientX: 1060 }))
      window.dispatchEvent(new Event('pointerup'))
    })
    expect(result.current.width).toBe(420)
    act(() => setWindow(1200))
    expect(result.current.width).toBe(420)
  })

  it('steps from the scaled width on the keyboard', () => {
    useSolSidebarStore.getState().reset()
    setWindow(1920)
    const { result } = renderHook(() => useSidebarResize())
    const key = {
      key: 'ArrowLeft',
      preventDefault: vi.fn()
    } as unknown as React.KeyboardEvent<HTMLElement>
    act(() => result.current.onKeyDown(key))
    expect(useSolSidebarStore.getState().width).toBe(438)
    expect(useSolSidebarStore.getState().userSized).toBe(true)
  })
})

describe('useWindowFit', () => {
  it('follows the window width across 1100px', () => {
    const { result } = renderHook(() => useWindowFit())
    expect(result.current).toBe('dock')
    act(() => {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: 900 })
      window.dispatchEvent(new Event('resize'))
    })
    expect(result.current).toBe('overlay')
  })
})

describe('motionMs', () => {
  it('is zero under reduced motion and the full time otherwise', () => {
    const original = window.matchMedia
    window.matchMedia = vi.fn(() => ({ matches: true }) as MediaQueryList)
    expect(motionMs(340)).toBe(0)
    window.matchMedia = vi.fn(() => ({ matches: false }) as MediaQueryList)
    expect(motionMs(340)).toBe(340)
    window.matchMedia = original
  })
})
