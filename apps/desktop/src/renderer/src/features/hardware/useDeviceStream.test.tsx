// SOLUSDEV-326 P3: the shell's one subscription to the project's device rows, and the plug-in toast.
import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { listDetectedDevices, type DetectedDeviceOut } from '../../lib/api/hardware'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceEvents } from '../graph/useWorkspaceEvents'
import { useShellStore } from '../workspace/shellStore'
import { device } from './testing/fixtures'
import { useDeviceStore } from './deviceStore'
import { useDeviceStream } from './useDeviceStream'

vi.mock('../graph/useWorkspaceEvents', () => ({ useWorkspaceEvents: vi.fn(() => null) }))
vi.mock('../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/hardware')>()),
  listDetectedDevices: vi.fn()
}))

/** The `onDevices` the hook handed to the project stream for `projectId`. */
function frame(projectId: string, devices: DetectedDeviceOut[]): void {
  const call = vi.mocked(useWorkspaceEvents).mock.calls.findLast(([id]) => id === projectId)
  act(() => call?.[3]?.(devices))
}

const refs = (): (string | null)[] => useDeviceStore.getState().devices.map((row) => row.device_ref)

beforeEach(() => {
  vi.clearAllMocks()
  useDeviceStore.getState().reset()
  useShellStore.getState().reset()
  useAuthStore.setState({ status: 'authenticated', accessToken: 'test-session' })
  vi.mocked(listDetectedDevices).mockResolvedValue([])
})

it('subscribes once to the project stream and seeds the rows from GET /detected', async () => {
  vi.mocked(listDetectedDevices).mockResolvedValue([device('usb_serial:A')])
  const view = renderHook(() => useDeviceStream('p1', 'home'))
  await act(async () => {})
  expect(listDetectedDevices).toHaveBeenCalledExactlyOnceWith('p1')
  expect(vi.mocked(useWorkspaceEvents).mock.calls.every(([id]) => id === 'p1')).toBe(true)
  expect(refs()).toEqual(['usb_serial:A'])
  view.rerender()
  expect(listDetectedDevices).toHaveBeenCalledOnce()
})

it('does nothing without a project', async () => {
  renderHook(() => useDeviceStream(null, 'home'))
  await act(async () => {})
  expect(listDetectedDevices).not.toHaveBeenCalled()
  expect(useWorkspaceEvents).toHaveBeenLastCalledWith(
    null,
    expect.any(Function),
    undefined,
    expect.any(Function)
  )
})

it('a frame replaces the rows, and a seed that lands after it is dropped', async () => {
  let land: (rows: DetectedDeviceOut[]) => void = () => undefined
  vi.mocked(listDetectedDevices).mockReturnValue(new Promise((resolve) => (land = resolve)))
  renderHook(() => useDeviceStream('p1', 'home'))
  frame('p1', [device('usb_serial:B')])
  await act(async () => land([device('usb_serial:OLD')]))
  expect(refs()).toEqual(['usb_serial:B'])
})

it('what was already plugged in when the rows first load raises no toast', async () => {
  vi.mocked(listDetectedDevices).mockResolvedValue([device('usb_serial:A')])
  renderHook(() => useDeviceStream('p1', 'home'))
  await act(async () => {})
  frame('p1', [device('usb_serial:A')])
  expect(useShellStore.getState().toast).toBeNull()
})

it('an arrival away from the Hardware screen raises one toast that opens Hardware', async () => {
  renderHook(() => useDeviceStream('p1', 'workspace'))
  await act(async () => {})
  frame('p1', [device('usb_serial:A', { state: 'inspecting' })])
  expect(useShellStore.getState().toast).toBeNull()
  frame('p1', [device('usb_serial:A')])
  expect(useShellStore.getState().toast).toMatchObject({
    title: 'Something was plugged in',
    action: 'Open Hardware',
    screen: 'hardware'
  })
  // The page owes SOL the notice the toast stood in for (usePlugInNotice sends it on opening).
  expect(useDeviceStore.getState().unannounced).toEqual(['usb_serial:A'])
  // The same row again is not another arrival.
  useShellStore.getState().clearToast()
  frame('p1', [device('usb_serial:A', { confidence: 0.9 })])
  expect(useShellStore.getState().toast).toBeNull()
})

it('raises no toast while the Hardware screen is the current screen', async () => {
  renderHook(() => useDeviceStream('p1', 'hardware'))
  await act(async () => {})
  frame('p1', [device('usb_serial:A')])
  expect(refs()).toEqual(['usb_serial:A'])
  expect(useShellStore.getState().toast).toBeNull()
  expect(useDeviceStore.getState().unannounced).toEqual([])
})

it('a failed seed leaves the rows empty and the stream still fills them', async () => {
  vi.mocked(listDetectedDevices).mockRejectedValue(new Error('offline'))
  renderHook(() => useDeviceStream('p1', 'home'))
  await act(async () => {})
  expect(refs()).toEqual([])
  frame('p1', [device('usb_serial:A')])
  expect(refs()).toEqual(['usb_serial:A'])
})

it('drops the rows when the project changes, and a late seed of the old project never lands', async () => {
  let land: (rows: DetectedDeviceOut[]) => void = () => undefined
  vi.mocked(listDetectedDevices).mockReturnValueOnce(new Promise((resolve) => (land = resolve)))
  const view = renderHook(({ id }) => useDeviceStream(id, 'home'), { initialProps: { id: 'p1' } })
  frame('p1', [device('usb_serial:A')])
  view.rerender({ id: 'p2' })
  await act(async () => land([device('usb_serial:OLD')]))
  expect(useDeviceStore.getState()).toMatchObject({ projectId: 'p2', devices: [] })
})
