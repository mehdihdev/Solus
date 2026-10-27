// SOLUSDEV-319 drive slices 3/3b (docs/architecture/sol-drive.md §2.1, §5):
// the Electron glue that connects the drive pieces — controller (status +
// consent), the agent (SMAppService registration packaged, a `serve` child in
// dev, the socket client), the companion (env at spawn, the session line,
// stdout geometry), the outline session and the IPC. Everything with logic
// lives in the pure modules beside this one.
import { app, shell, type IpcMainInvokeEvent } from 'electron'
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync } from 'node:fs'
import { userInfo } from 'node:os'
import { dirname } from 'node:path'
import {
  notifyCompanionDriveChanged,
  onCompanionDriveWindow,
  setCompanionDriveResolver,
  setCompanionDriveSessionSource
} from '../companion'
import { linkedWorkspaces, realLocalStateDeps } from '../localState'
import type { SolSettings } from '../solSettings'
import type { SolWindowIpc, SolWindowManager } from '../sol-window/solWindow'
import { SOL_WINDOW_CHANNELS } from '../sol-window/solWindow.constants'
import { requestAgentSession, requestAgentTrust } from './driveAgentClient'
import {
  createAgentRegistration,
  DRIVE_LOGIN_ITEMS_URL,
  type LoginItemsApi
} from './driveAgentRegistration'
import { createDriveController } from './driveController'
import { createDevAgentSupervisor } from './driveDevAgent'
import {
  driveSocketPaths,
  isSafeHelperPath,
  packagedDriveFiles,
  realHelperFs,
  resolveDevHelper
} from './driveHelper'
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

const warn = (message: string): void => console.warn(message)

/** A regular file, not a link — what the bundle must contain (packaged). */
const isPlainFile = (path: string): boolean => {
  const info = realHelperFs.lstat(path)
  return info !== null && info.isFile && !info.isSymbolicLink
}

/** Where the agent runs from, and whether it is installed. */
function agentHost(): {
  socket: { dir: string; socket: string }
  devHelper(): string | null
  installed(): boolean
} {
  const socket = driveSocketPaths({ isPackaged: app.isPackaged, home: userInfo().homedir })
  const devHelper = (): string | null =>
    resolveDevHelper({
      appPath: app.getAppPath(),
      exists: existsSync,
      realpath: realLocalStateDeps.realpath
    })
  const installed = (): boolean => {
    if (app.isPackaged) {
      const files = packagedDriveFiles(process.resourcesPath)
      return isPlainFile(files.helper) && isPlainFile(files.plist)
    }
    const helper = devHelper()
    return helper !== null && isSafeHelperPath(helper, realHelperFs)
  }
  return { socket, devHelper, installed }
}

export function startDrive(opts: {
  ipc: SolWindowIpc
  settings: SolSettings
  windows: Pick<SolWindowManager, 'broadcast'>
  isAllowedSender: (event: IpcMainInvokeEvent) => boolean
  /** The main renderer only — consent actions (drive on, `trust --prompt`, approval pane). */
  isMainSender: (event: IpcMainInvokeEvent) => boolean
}): DriveHandle {
  const host = agentHost()
  const session = createDriveSession({
    createStrip: createOutlineStrip,
    now: Date.now,
    setTimeout: (cb, ms) => setTimeout(cb, ms),
    clearTimeout: (handle) => clearTimeout(handle as NodeJS.Timeout)
  })
  const registration = createAgentRegistration(app as unknown as LoginItemsApi, warn)
  const devAgent = createDevAgentSupervisor({
    spawn: (command, args, options) => spawn(command, args, options),
    // The agent creates and checks `drive-dev/` itself; its parent must exist.
    prepareDir: (dir) => void mkdirSync(dirname(dir), { recursive: true, mode: 0o700 }),
    setTimeout: (cb, ms) => setTimeout(cb, ms),
    clearTimeout: (handle) => clearTimeout(handle as NodeJS.Timeout),
    now: Date.now
  })
  const onAgentWanted = (wanted: boolean): void => {
    if (process.platform !== 'darwin') return
    if (app.isPackaged) return registration.apply(wanted)
    const helper = wanted ? host.devHelper() : null
    devAgent.set(helper === null ? null : { helper, socketDir: host.socket.dir })
  }
  const controller = createDriveController({
    platform: process.platform,
    installed: host.installed,
    socketPath: () => host.socket.socket,
    trust: (prompt) => requestAgentTrust(host.socket.socket, prompt),
    agentState: () => (app.isPackaged ? registration.state() : null),
    onAgentWanted,
    linkedFolders: () => linkedWorkspaces(realLocalStateDeps),
    realpath: realLocalStateDeps.realpath,
    settings: opts.settings,
    now: Date.now,
    broadcast: (status) => opts.windows.broadcast(SOL_WINDOW_CHANNELS.driveStatus, status),
    onCompanionDriveChanged: notifyCompanionDriveChanged
  })
  setCompanionDriveResolver((projectId) => controller.companionDrive(projectId))
  setCompanionDriveSessionSource((socket) => requestAgentSession(socket))
  onCompanionDriveWindow((bounds) => session.setBounds(bounds))
  registerDriveIpcHandlers(
    opts.ipc,
    {
      status: () => controller.status(),
      setDrive: (on) => controller.setDrive(on),
      requestPermissions: () => controller.requestPermissions(),
      setDriving: (senderId, active) => session.setDriving(senderId, active),
      releaseSender: (senderId) => session.releaseSender(senderId),
      openApproval: () =>
        void shell.openExternal(DRIVE_LOGIN_ITEMS_URL).catch((error: unknown) => {
          warn(`[drive] could not open Login Items: ${String(error)}`)
        })
    },
    { isAllowedSender: opts.isAllowedSender, isMainSender: opts.isMainSender }
  )
  // First evaluation: clears an agent registration (or dev helper) a previous
  // run left behind while the setting is now off.
  controller.refresh()
  return {
    setProject: (projectId) => controller.setProject(projectId),
    refresh: () => controller.refresh(),
    isQuiet: () => session.isQuiet(),
    dispose: () => {
      onCompanionDriveWindow(null)
      setCompanionDriveSessionSource(null)
      devAgent.set(null)
      session.dispose()
    }
  }
}
