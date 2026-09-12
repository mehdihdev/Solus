// The machine-wide detected-device list (GET /hardware/detected is host-scoped),
// seeded once per workspace mount and then replaced by SSE `hardware.devices_changed`
// frames. `devices === null` means never seeded — an honest "unknown", not "none".
import { create } from 'zustand'
import type { DetectedDeviceOut } from '../../../lib/api/hardware'

export interface DetectedDevicesState {
  devices: DetectedDeviceOut[] | null
  updatedAt: number | null
  setDevices: (devices: DetectedDeviceOut[]) => void
  reset: () => void
}

export const useDetectedDevicesStore = create<DetectedDevicesState>()((set) => ({
  devices: null,
  updatedAt: null,
  // ponytail: strictly monotonic so two frames in one millisecond still read as
  // distinct updates (the modal's watermark compares by equality).
  setDevices: (devices) =>
    set((state) => ({
      devices: [...devices],
      updatedAt: Math.max(Date.now(), (state.updatedAt ?? 0) + 1)
    })),
  reset: () => set({ devices: null, updatedAt: null })
}))

export function useDetectedDevices(): Pick<DetectedDevicesState, 'devices' | 'updatedAt'> {
  const devices = useDetectedDevicesStore((state) => state.devices)
  const updatedAt = useDetectedDevicesStore((state) => state.updatedAt)
  return { devices, updatedAt }
}
