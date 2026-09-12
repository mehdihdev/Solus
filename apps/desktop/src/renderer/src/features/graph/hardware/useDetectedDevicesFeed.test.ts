import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { listDetectedDevices, type DetectedDeviceOut } from '../../../lib/api/hardware'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { useDetectedDevicesStore } from './detectedDevicesStore'
import { useDetectedDevicesFeed } from './useDetectedDevicesFeed'

vi.mock('../../../lib/api/hardware', () => ({ listDetectedDevices: vi.fn() }))
const device = { device_ref: 'usb:fixture', transport: 'usb_serial' } as DetectedDeviceOut
beforeEach(() => {
  vi.clearAllMocks()
  useDetectedDevicesStore.getState().reset()
  useWorkspaceStore.setState({ project: { id: 'A', name: 'A' } })
})

it.each([{ frame: [] }, { frame: [device] }])(
  'does not overwrite a newer authoritative frame with a late seed',
  async ({ frame }) => {
    let resolve!: (devices: DetectedDeviceOut[]) => void
    vi.mocked(listDetectedDevices).mockReturnValue(
      new Promise((done) => {
        resolve = done
      })
    )
    const { result } = renderHook(() => useDetectedDevicesFeed('A'))
    act(() => result.current.seed())
    act(() => result.current.onDevices(frame))
    await act(async () => resolve([{ ...device, device_ref: 'usb:stale' }]))
    expect(useDetectedDevicesStore.getState().devices).toEqual(frame)
  }
)

it.each([false, true])(
  'permanently expires a seed across A to B to A, unmounted=%s',
  async (end) => {
    let resolve!: (devices: DetectedDeviceOut[]) => void
    vi.mocked(listDetectedDevices).mockReturnValue(
      new Promise((done) => {
        resolve = done
      })
    )
    const { result, unmount } = renderHook(() => useDetectedDevicesFeed('A'))
    act(() => result.current.seed())
    act(() => {
      useWorkspaceStore.setState({ project: { id: 'B', name: 'B' } })
      useWorkspaceStore.setState({ project: { id: 'A', name: 'A' } })
    })
    if (end) unmount()
    await act(async () => resolve([device]))
    expect(useDetectedDevicesStore.getState().devices).toBeNull()
  }
)
