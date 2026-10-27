// SOLUSDEV-319 drive slice 3: "SOL can use your mouse and keyboard" as Settings
// reads it — main-owned (`sol.drive` in ~/.solus/config.json) over the drive
// members of window.solus.sol. getDriveStatus on mount, then every push; main
// is the source of truth, so every call adopts the status it returns.
import { useCallback, useEffect, useState } from 'react'
import type { DriveBridge, DriveStatus } from '../../lib/driveBridge'
import { SOL_APPLY_ERROR } from './useDesktopSol'

export const DRIVE_LOAD_ERROR =
  "The mouse and keyboard setting didn't load from the desktop app — reopen Settings to retry."
export const DRIVE_APPLY_ERROR = SOL_APPLY_ERROR

export interface DriveSettings {
  /** Null without the drive bridge, or until main answers. */
  status: DriveStatus | null
  error: string | null
  setDrive: (on: boolean) => void
  /** Ask macOS for the helper's grants (`trust --prompt`). */
  requestPermissions: () => void
}

export function useDriveStatus(bridge: DriveBridge | null): DriveSettings {
  const [status, setStatus] = useState<DriveStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const run = useCallback((p: Promise<DriveStatus | null>, failure: string): void => {
    const adopt = (next: DriveStatus | null): void => {
      if (next) setStatus(next)
      setError(next ? null : failure)
    }
    void p.then(adopt, () => adopt(null))
  }, [])
  useEffect(() => {
    if (!bridge) return
    run(bridge.getDriveStatus(), DRIVE_LOAD_ERROR)
    return bridge.onDriveStatus((next) => {
      setStatus(next)
      setError(null)
    })
  }, [bridge, run])
  return {
    status,
    error,
    setDrive: (on) => {
      if (bridge) run(bridge.setDrive(on), DRIVE_APPLY_ERROR)
    },
    requestPermissions: () => {
      if (bridge) run(bridge.requestDrivePermissions(), DRIVE_APPLY_ERROR)
    }
  }
}
