import { beforeEach, expect, it } from 'vitest'
import type { DetectedDeviceOut } from '../../../lib/api/hardware'
import { useDetectedDevicesStore } from './detectedDevicesStore'

const device: DetectedDeviceOut = {
  transport: 'usb_serial',
  device_ref: 'usb_serial:AB12',
  identity: null,
  level: 'board',
  board: null,
  board_class: null,
  mcu_known: true,
  confidence: 0.5,
  evidence: [],
  ambiguous: false,
  last_seen_path: null
}

beforeEach(() => useDetectedDevicesStore.getState().reset())

it('starts unseeded, round-trips a device list and advances updatedAt', () => {
  expect(useDetectedDevicesStore.getState()).toMatchObject({ devices: null, updatedAt: null })
  useDetectedDevicesStore.getState().setDevices([device])
  const first = useDetectedDevicesStore.getState()
  expect(first.devices).toEqual([device])
  expect(first.updatedAt).toEqual(expect.any(Number))
  useDetectedDevicesStore.getState().setDevices([])
  const second = useDetectedDevicesStore.getState()
  expect(second.devices).toEqual([])
  expect(second.devices).not.toBe(first.devices)
  expect(second.updatedAt ?? 0).toBeGreaterThan(first.updatedAt ?? Infinity)
})

it('reset returns to the unseeded state', () => {
  useDetectedDevicesStore.getState().setDevices([device])
  useDetectedDevicesStore.getState().reset()
  expect(useDetectedDevicesStore.getState()).toMatchObject({ devices: null, updatedAt: null })
})
