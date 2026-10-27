// SOLUSDEV-319 drive slice 3 test fixtures: a DriveStatus and an in-memory
// DriveBridge whose pushes the test drives by hand.
import { vi } from 'vitest'
import type { DriveBridge, DriveStatus } from '../../lib/driveBridge'

export const DRIVE_STATUS: DriveStatus = {
  enabled: false,
  available: true,
  reason: null,
  trust: { accessibility: true, screenRecording: true },
  unsignedDev: false,
  agent: 'enabled'
}

export function driveStatus(overrides: Partial<DriveStatus> = {}): DriveStatus {
  return { ...DRIVE_STATUS, ...overrides }
}

export interface FakeDriveBridge extends DriveBridge {
  pushStatus: (s: DriveStatus) => void
}

export function fakeDriveBridge(status: DriveStatus | null = DRIVE_STATUS): FakeDriveBridge {
  let handler: ((s: DriveStatus) => void) | null = null
  return {
    getDriveStatus: vi.fn(async () => status),
    setDrive: vi.fn(async (on: boolean) => (status ? { ...status, enabled: on } : null)),
    requestDrivePermissions: vi.fn(async () => status),
    setDriving: vi.fn(async () => undefined),
    openDriveApproval: vi.fn(async () => undefined),
    onDriveStatus: vi.fn((h: (s: DriveStatus) => void) => {
      handler = h
      return () => {
        handler = null
      }
    }),
    pushStatus: (s) => handler?.(s)
  }
}
