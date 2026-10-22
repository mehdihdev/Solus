import { describe, it, expect, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useDesktopSol, SOL_APPLY_ERROR, SOL_LOAD_ERROR } from './useDesktopSol'
import { fakeSolBridge, SOL_STATE } from '../sol/solWindow.fixtures'

describe('useDesktopSol', () => {
  it('is inert without a bridge (browser preview)', () => {
    const { result } = renderHook(() => useDesktopSol(null))
    expect(result.current.state).toBeNull()
    expect(result.current.available).toBe(false)
  })

  it('reads the state on mount and follows pushes', async () => {
    const bridge = fakeSolBridge()
    const { result } = renderHook(() => useDesktopSol(bridge))
    await waitFor(() => expect(result.current.state).toEqual(SOL_STATE))
    act(() => bridge.pushState({ ...SOL_STATE, hotkeysEnabled: false }))
    expect(result.current.state?.hotkeysEnabled).toBe(false)
  })

  it('names a load failure plainly', async () => {
    const bridge = fakeSolBridge(null)
    const { result } = renderHook(() => useDesktopSol(bridge))
    await waitFor(() => expect(result.current.error).toBe(SOL_LOAD_ERROR))
  })

  it('adopts what an applied change returns, or says main refused it', async () => {
    const bridge = fakeSolBridge()
    const { result } = renderHook(() => useDesktopSol(bridge))
    await waitFor(() => expect(result.current.state).not.toBeNull())
    vi.mocked(bridge.setHotkeys).mockResolvedValueOnce(null)
    act(() => result.current.apply((b) => b.setHotkeys(false)))
    await waitFor(() => expect(result.current.error).toBe(SOL_APPLY_ERROR))
  })

  it('opens the capture pane and rechecks through the bridge', async () => {
    const bridge = fakeSolBridge()
    const { result } = renderHook(() => useDesktopSol(bridge))
    await waitFor(() => expect(result.current.state).not.toBeNull())
    act(() => result.current.openCaptureSettings())
    act(() => result.current.recheck())
    expect(bridge.openCaptureSettings).toHaveBeenCalledTimes(1)
    // getState: once on mount, once for the recheck.
    expect(bridge.getState).toHaveBeenCalledTimes(2)
  })
})
