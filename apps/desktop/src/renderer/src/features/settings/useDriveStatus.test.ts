import { describe, it, expect, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { DRIVE_APPLY_ERROR, DRIVE_LOAD_ERROR, useDriveStatus } from './useDriveStatus'
import { driveStatus, fakeDriveBridge } from './drive.fixtures'
import type { DriveBridge } from '../../lib/driveBridge'

describe('useDriveStatus', () => {
  it('is inert without the drive bridge', () => {
    const { result } = renderHook(() => useDriveStatus(null))
    expect(result.current.status).toBeNull()
    expect(result.current.error).toBeNull()
  })

  it('reads the status on mount and follows pushes', async () => {
    const bridge = fakeDriveBridge()
    const { result } = renderHook(() => useDriveStatus(bridge))
    await waitFor(() => expect(result.current.status?.available).toBe(true))
    act(() => bridge.pushStatus(driveStatus({ enabled: true })))
    expect(result.current.status?.enabled).toBe(true)
  })

  it('names a load failure plainly', async () => {
    const { result } = renderHook(() => useDriveStatus(fakeDriveBridge(null)))
    await waitFor(() => expect(result.current.error).toBe(DRIVE_LOAD_ERROR))
  })

  it('turns driving on through the bridge and adopts what main returns', async () => {
    const bridge = fakeDriveBridge()
    const { result } = renderHook(() => useDriveStatus(bridge))
    await waitFor(() => expect(result.current.status).not.toBeNull())
    act(() => result.current.setDrive(true))
    expect(bridge.setDrive).toHaveBeenCalledWith(true)
    await waitFor(() => expect(result.current.status?.enabled).toBe(true))
  })

  it('says main refused a change', async () => {
    const bridge = fakeDriveBridge()
    const { result } = renderHook(() => useDriveStatus(bridge))
    await waitFor(() => expect(result.current.status).not.toBeNull())
    vi.mocked(bridge.setDrive).mockRejectedValueOnce(new Error('no'))
    act(() => result.current.setDrive(true))
    await waitFor(() => expect(result.current.error).toBe(DRIVE_APPLY_ERROR))
  })

  it('asks for the helper permissions through the bridge', async () => {
    const bridge = fakeDriveBridge()
    const { result } = renderHook(() => useDriveStatus(bridge))
    await waitFor(() => expect(result.current.status).not.toBeNull())
    act(() => result.current.requestPermissions())
    expect(bridge.requestDrivePermissions).toHaveBeenCalledTimes(1)
  })

  it('unsubscribes on unmount', () => {
    const bridge = fakeDriveBridge()
    const { unmount } = renderHook(() => useDriveStatus(bridge))
    unmount()
    act(() => bridge.pushStatus(driveStatus({ enabled: true })))
    expect(bridge.onDriveStatus).toHaveBeenCalledTimes(1)
  })
})

describe('useDriveStatus — rereads on return', () => {
  it('rereads the status when the window regains focus or becomes visible', async () => {
    const bridge = fakeDriveBridge()
    renderHook(() => useDriveStatus(bridge))
    await waitFor(() => expect(bridge.getDriveStatus).toHaveBeenCalledTimes(1))
    act(() => {
      window.dispatchEvent(new Event('focus'))
    })
    expect(bridge.getDriveStatus).toHaveBeenCalledTimes(2)
    const visibility = vi.spyOn(document, 'visibilityState', 'get')
    visibility.mockReturnValue('hidden')
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(bridge.getDriveStatus).toHaveBeenCalledTimes(2)
    visibility.mockReturnValue('visible')
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(bridge.getDriveStatus).toHaveBeenCalledTimes(3)
    visibility.mockRestore()
  })

  it('stops rereading after unmount', async () => {
    const bridge = fakeDriveBridge()
    const { unmount } = renderHook(() => useDriveStatus(bridge))
    await waitFor(() => expect(bridge.getDriveStatus).toHaveBeenCalledTimes(1))
    unmount()
    window.dispatchEvent(new Event('focus'))
    expect(bridge.getDriveStatus).toHaveBeenCalledTimes(1)
  })
})

describe('useDriveStatus — Login Items approval (slice 3b)', () => {
  it('opens the Login Items pane through the bridge', async () => {
    const bridge = fakeDriveBridge()
    const { result } = renderHook(() => useDriveStatus(bridge))
    await waitFor(() => expect(result.current.status).not.toBeNull())
    act(() => result.current.openApproval())
    expect(bridge.openDriveApproval).toHaveBeenCalledTimes(1)
  })

  it('says so when main cannot open it', async () => {
    const bridge = fakeDriveBridge()
    vi.mocked(bridge.openDriveApproval!).mockRejectedValueOnce(new Error('no'))
    const { result } = renderHook(() => useDriveStatus(bridge))
    await waitFor(() => expect(result.current.status).not.toBeNull())
    act(() => result.current.openApproval())
    await waitFor(() => expect(result.current.error).toBe(DRIVE_APPLY_ERROR))
  })

  it('is a no-op when the preload lacks the member', async () => {
    const bridge: DriveBridge = { ...fakeDriveBridge() }
    delete bridge.openDriveApproval
    const { result } = renderHook(() => useDriveStatus(bridge))
    await waitFor(() => expect(result.current.status).not.toBeNull())
    expect(() => act(() => result.current.openApproval())).not.toThrow()
  })
})
