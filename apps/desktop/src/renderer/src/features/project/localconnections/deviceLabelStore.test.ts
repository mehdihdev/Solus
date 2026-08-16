// SOLUSDEV-72 — per-device user labels ("leader"/"follower"). Keyed by
// serial_number; the vid:pid:device_path fallback exists ONLY for serial-less
// devices and is marked unverified-after-replug in the UI.
import { describe, it, expect, beforeEach } from 'vitest'
import {
  deviceLabelKey,
  isUnverifiedAfterReplug,
  useDeviceLabelStore,
  DEVICE_LABELS_STORAGE_KEY
} from './deviceLabelStore'

const WITH_SERIAL = {
  serial_number: '5B42135040',
  vid: '1a86',
  pid: '55d3',
  device_path: '/dev/ttyACM0'
}
const NO_SERIAL = { serial_number: null, vid: '1a86', pid: '55d3', device_path: '/dev/ttyACM1' }

beforeEach(() => {
  useDeviceLabelStore.setState({ labels: {} })
  localStorage.removeItem(DEVICE_LABELS_STORAGE_KEY)
})

describe('deviceLabelKey', () => {
  it('keys by serial number when the device has one', () => {
    expect(deviceLabelKey(WITH_SERIAL)).toBe('5B42135040')
  })

  it('falls back to vid:pid:device_path only when serial is null', () => {
    expect(deviceLabelKey(NO_SERIAL)).toBe('1a86:55d3:/dev/ttyACM1')
  })
})

describe('isUnverifiedAfterReplug', () => {
  it('is true only for serial-less devices (path keys can rebind on replug)', () => {
    expect(isUnverifiedAfterReplug(WITH_SERIAL)).toBe(false)
    expect(isUnverifiedAfterReplug(NO_SERIAL)).toBe(true)
  })
})

describe('useDeviceLabelStore', () => {
  it('sets a label immutably under the given key', () => {
    const before = useDeviceLabelStore.getState().labels
    useDeviceLabelStore.getState().setLabel('5B42135040', 'leader')
    expect(useDeviceLabelStore.getState().labels['5B42135040']).toBe('leader')
    expect(before).toEqual({})
  })

  it('clears a label when set to blank', () => {
    useDeviceLabelStore.getState().setLabel('5B42135040', 'leader')
    useDeviceLabelStore.getState().setLabel('5B42135040', '   ')
    expect(useDeviceLabelStore.getState().labels['5B42135040']).toBeUndefined()
  })

  it('keeps labels for other devices untouched', () => {
    useDeviceLabelStore.getState().setLabel('A', 'leader')
    useDeviceLabelStore.getState().setLabel('B', 'follower')
    useDeviceLabelStore.getState().setLabel('A', '')
    expect(useDeviceLabelStore.getState().labels).toEqual({ B: 'follower' })
  })
})
