// SOLUSDEV-319 slice 4 (sol-drive.md §2.2): the pill holds main's latest
// front-app snapshot while it is mounted — subscribed on mount, unsubscribed
// (and forgotten) on unmount; a bridge without onFrontApp is tolerated.
import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SolFrontApp } from '../../../../main/drive/frontAppShape'
import type { SolBridge } from '../../lib/desktopBridge'
import { useFrontAppSnapshot, useSolWindowStore } from './solWindowStore'

const FREECAD: SolFrontApp = {
  drivable: true,
  binding: 'window',
  bundleId: 'org.freecad.FreeCAD',
  name: 'FreeCAD',
  pid: 4242,
  windowId: 77,
  title: 'bracket_v3.FCStd'
}

function frontBridge(): {
  bridge: Pick<SolBridge, 'onFrontApp'>
  push: (front: SolFrontApp | null) => void
  off: ReturnType<typeof vi.fn>
} {
  let handler: ((front: SolFrontApp | null) => void) | null = null
  const off = vi.fn(() => {
    handler = null
  })
  const bridge = {
    onFrontApp: vi.fn((h: (front: SolFrontApp | null) => void) => {
      handler = h
      return off
    })
  }
  return { bridge, push: (front) => handler?.(front), off }
}

afterEach(() => useSolWindowStore.setState({ frontApp: null }))

describe('useFrontAppSnapshot', () => {
  it('mirrors pushes, then unsubscribes and forgets the snapshot on unmount', () => {
    const { bridge, push, off } = frontBridge()
    const { unmount } = renderHook(() => useFrontAppSnapshot(bridge))
    expect(bridge.onFrontApp).toHaveBeenCalledTimes(1)
    act(() => push(FREECAD))
    expect(useSolWindowStore.getState().frontApp).toEqual(FREECAD)
    act(() => push(null))
    expect(useSolWindowStore.getState().frontApp).toBeNull()
    act(() => push(FREECAD))
    unmount()
    expect(off).toHaveBeenCalledTimes(1)
    expect(useSolWindowStore.getState().frontApp).toBeNull()
  })

  it('tolerates no bridge and a bridge without onFrontApp', () => {
    expect(() => renderHook(() => useFrontAppSnapshot(null)).unmount()).not.toThrow()
    expect(() => renderHook(() => useFrontAppSnapshot({})).unmount()).not.toThrow()
    expect(useSolWindowStore.getState().frontApp).toBeNull()
  })
})
