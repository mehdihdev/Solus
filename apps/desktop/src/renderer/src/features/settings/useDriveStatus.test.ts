import { describe, it, expect, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { DRIVE_APPLY_ERROR, DRIVE_LOAD_ERROR, useDriveStatus } from './useDriveStatus'
import { driveStatus, fakeDriveBridge } from './drive.fixtures'

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
