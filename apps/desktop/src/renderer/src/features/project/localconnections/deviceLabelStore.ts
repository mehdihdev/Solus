// Per-device user labels ("leader"/"follower") — SOLUSDEV-72. Persisted
// locally, keyed by serial_number (stable across replugs). A serial-less
// device falls back to `vid:pid:device_path`, which the OS can reassign on
// replug — the UI marks those bindings "unverified after replug".
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { BenchDevice } from '../../../lib/api/resources'

export const DEVICE_LABELS_STORAGE_KEY = 'solus_device_labels_v1'

type DeviceIdentity = Pick<BenchDevice, 'serial_number' | 'vid' | 'pid' | 'device_path'>

/** Stable identity key: serial first; vid:pid:path only when serial is null. */
export function deviceLabelKey(device: DeviceIdentity): string {
  return device.serial_number ?? `${device.vid}:${device.pid}:${device.device_path}`
}

/** True when the key can silently rebind after a replug (no serial to pin it). */
export function isUnverifiedAfterReplug(device: Pick<BenchDevice, 'serial_number'>): boolean {
  return device.serial_number === null
}

interface DeviceLabelState {
  labels: Record<string, string>
  /** Blank label removes the entry. Always immutable updates. */
  setLabel: (key: string, label: string) => void
}

export const useDeviceLabelStore = create<DeviceLabelState>()(
  persist(
    (set) => ({
      labels: {},
      setLabel: (key, label) =>
        set((state) => {
          const trimmed = label.trim()
          if (!trimmed) {
            // Delete on a fresh copy — the previous state object is untouched.
            const rest = { ...state.labels }
            delete rest[key]
            return { labels: rest }
          }
          return { labels: { ...state.labels, [key]: label } }
        })
    }),
    { name: DEVICE_LABELS_STORAGE_KEY }
  )
)
