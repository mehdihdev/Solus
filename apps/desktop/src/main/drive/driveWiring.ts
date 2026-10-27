// SOLUSDEV-319 drive slice 3 (docs/architecture/sol-drive.md §5): the Electron
// glue that connects the drive pieces — controller (status + consent), the
// companion (env at spawn, stdout geometry), the outline session and the IPC.
// Everything with logic lives in the pure modules beside this one.
import { app, type IpcMainInvokeEvent } from 'electron'
import { existsSync } from 'node:fs'
import {
  notifyCompanionDriveChanged,
  onCompanionDriveWindow,
  setCompanionDriveResolver
} from '../companion'
import { linkedWorkspaces, realLocalStateDeps } from '../localState'
import type { SolSettings } from '../solSettings'
import type { SolWindowIpc, SolWindowManager } from '../sol-window/solWindow'
import { SOL_WINDOW_CHANNELS } from '../sol-window/solWindow.constants'
import { createDriveController } from './driveController'
import { isExecutableFile, realTrustExec, resolveDriveHelper, runDriveTrust } from './driveHelper'
import { registerDriveIpcHandlers } from './driveIpc'
import { createDriveSession } from './driveOutline'
import { createOutlineStrip } from './driveOutlineWindow'

export interface DriveHandle {
  /** The renderer's active project (bridge:project). */
  setProject(projectId: string | null): void
  /** A folder link changed (any project's). */
  refresh(): void
  /** The hotkey detectors' quiet period. */
  isQuiet(): boolean
  dispose(): void
}

export function startDrive(opts: {
  ipc: SolWindowIpc
  settings: SolSettings
  windows: Pick<SolWindowManager, 'broadcast'>
  isAllowedSender: (event: IpcMainInvokeEvent) => boolean
}): DriveHandle {
  const session = createDriveSession({
    createStrip: createOutlineStrip,
    now: Date.now,
    setTimeout: (cb, ms) => setTimeout(cb, ms),
    clearTimeout: (handle) => clearTimeout(handle as NodeJS.Timeout)
  })
  const controller = createDriveController({
    platform: process.platform,
    helperPath: () =>
      resolveDriveHelper({
        isPackaged: app.isPackaged,
        resourcesPath: process.resourcesPath,
        appPath: app.getAppPath(),
        exists: existsSync,
        realpath: realLocalStateDeps.realpath
      }),
    isExecutable: isExecutableFile,
    linkedFolders: () => linkedWorkspaces(realLocalStateDeps),
    realpath: realLocalStateDeps.realpath,
    runTrust: (helper, prompt) => runDriveTrust(helper, prompt, realTrustExec),
    settings: opts.settings,
    now: Date.now,
    broadcast: (status) => opts.windows.broadcast(SOL_WINDOW_CHANNELS.driveStatus, status),
    onCompanionDriveChanged: notifyCompanionDriveChanged
  })
  setCompanionDriveResolver((projectId) => controller.companionDrive(projectId))
  onCompanionDriveWindow((bounds) => session.setBounds(bounds))
  registerDriveIpcHandlers(
    opts.ipc,
    {
      status: () => controller.status(),
      setDrive: (on) => controller.setDrive(on),
      requestPermissions: () => controller.requestPermissions(),
      setDriving: (active) => session.setDriving(active)
    },
    opts.isAllowedSender
  )
  return {
    setProject: (projectId) => controller.setProject(projectId),
    refresh: () => controller.refresh(),
    isQuiet: () => session.isQuiet(),
    dispose: () => {
      onCompanionDriveWindow(null)
      session.dispose()
    }
  }
}
