// SOLUSDEV-326 P3: the shell's one copy of the plugged-in device rows, and what counts as an arrival.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { device } from './testing/fixtures'
import { arrivedDevices, useDeviceStore } from './deviceStore'

beforeEach(() => useDeviceStore.getState().reset())

describe('deviceStore', () => {
  it('starts with no rows and no project', () => {
    expect(useDeviceStore.getState()).toMatchObject({ projectId: null, devices: [] })
  })

  it('keeps the latest rows for the project that sent them', () => {
    useDeviceStore.getState().setDevices('p1', [device('usb_serial:A')])
    useDeviceStore.getState().setDevices('p1', [device('usb_serial:B')])
    expect(useDeviceStore.getState().projectId).toBe('p1')
    expect(useDeviceStore.getState().devices.map((row) => row.device_ref)).toEqual(['usb_serial:B'])
  })

  it('reset drops the rows (project switch, sign-out)', () => {
    useDeviceStore.getState().setDevices('p1', [device('usb_serial:A')])
    useDeviceStore.getState().reset()
    expect(useDeviceStore.getState()).toMatchObject({ projectId: null, devices: [] })
  })
})

describe('the devices that left while watched', () => {
  const OWNER = { last_seen: '2026-11-14T00:00:00Z' }

  it('keeps a remembered row that left, stamped with the time it left', () => {
    vi.useFakeTimers({ now: new Date('2026-11-16T10:00:00Z') })
    useDeviceStore.getState().setDevices('p1', [device('usb:A', { ...OWNER, bound_to: 'r1' })])
    useDeviceStore.getState().setDevices('p1', [])
    vi.useRealTimers()
    expect(useDeviceStore.getState().left).toEqual([
      device('usb:A', { bound_to: 'r1', last_seen: '2026-11-16T10:00:00.000Z' })
    ])
  })

  it('forgets it when it is plugged in again', () => {
    useDeviceStore.getState().setDevices('p1', [device('usb:A', OWNER)])
    useDeviceStore.getState().setDevices('p1', [])
    useDeviceStore.getState().setDevices('p1', [device('usb:A', OWNER)])
    expect(useDeviceStore.getState().left).toEqual([])
  })

  it('keeps nothing for a reader the memory does not reach (no last_seen on the row)', () => {
    useDeviceStore.getState().setDevices('p1', [device('usb:A')])
    useDeviceStore.getState().setDevices('p1', [])
    expect(useDeviceStore.getState().left).toEqual([])
  })

  it("another project's rows and a reset are not an unplug", () => {
    useDeviceStore.getState().setDevices('p1', [device('usb:A', OWNER)])
    useDeviceStore.getState().setDevices('p2', [])
    expect(useDeviceStore.getState().left).toEqual([])
    useDeviceStore.getState().setDevices('p2', [device('usb:A', OWNER)])
    useDeviceStore.getState().reset()
    expect(useDeviceStore.getState().left).toEqual([])
  })
})

describe('arrivedDevices', () => {
  it('names a settled, unbound, undismissed row that was not there before', () => {
    const next = [device('usb_serial:A'), device('usb_serial:B', { state: 'busy' })]
    expect(arrivedDevices([device('usb_serial:A')], next).map((row) => row.device_ref)).toEqual([
      'usb_serial:B'
    ])
  })

  it.each(['inspected', 'busy', 'unknown'] as const)('counts the settled state %s', (state) => {
    expect(arrivedDevices([], [device('usb_serial:A', { state })])).toHaveLength(1)
  })

  it('waits while the row is still being inspected, then counts it once it settles', () => {
    const inspecting = [device('usb_serial:A', { state: 'inspecting' })]
    expect(arrivedDevices([], inspecting)).toEqual([])
    expect(arrivedDevices(inspecting, [device('usb_serial:A')])).toHaveLength(1)
  })

  it('never names the same settled row twice', () => {
    const rows = [device('usb_serial:A')]
    expect(arrivedDevices(rows, [device('usb_serial:A', { confidence: 0.9 })])).toEqual([])
  })

  it('ignores bound, dismissed, unowed (null state) and ref-less rows', () => {
    const next = [
      device('usb_serial:A', { bound_to: 'e1' }),
      device('usb_serial:B', { dismissed: true }),
      device('usb_serial:C', { state: null }),
      { ...device('usb_serial:D'), state: undefined },
      { ...device('x'), device_ref: null }
    ]
    expect(arrivedDevices([], next)).toEqual([])
  })

  it('counts a device again after it was unplugged', () => {
    expect(arrivedDevices([], [device('usb_serial:A')])).toHaveLength(1)
  })
})
