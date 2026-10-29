// SOLUSDEV-319 drive slices 3/3b (docs/architecture/sol-drive.md §2.1, §5;
// ADR-041 amendment 2026-10-28): the Electron glue that connects the drive
// pieces — controller (status + consent), the agent (SMAppService registration,
// packaged), the transport (the XPC native module packaged, the debug helper in
// dev), the companion (env at spawn, the relay, stdout geometry), the outline
// session and the IPC. Everything with logic lives in the pure modules beside
// this one.
import { app, shell, type IpcMainInvokeEvent } from 'electron'
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import {
  notifyCompanionDriveChanged,
  onCompanionDriveWindow,
  setCompanionDriveResolver,
  setCompanionDriveTransport
} from '../companion'
import { linkedWorkspaces, realLocalStateDeps } from '../localState'
import type { SolSettings } from '../solSettings'
import type { SolWindowIpc, SolWindowManager } from '../sol-window/solWindow'
import { SOL_WINDOW_CHANNELS } from '../sol-window/solWindow.constants'
import {
  createAgentRegistration,
  DRIVE_LOGIN_ITEMS_URL,
  type LoginItemsApi
} from './driveAgentRegistration'
import { createDriveController } from './driveController'
import {
  isSafeHelperPath,
  packagedDriveFiles,
  parseTrustOutput,
  realHelperFs,
  resolveDevHelper,
  type DriveTrustResult
} from './driveHelper'
import { registerDriveIpcHandlers } from './driveIpc'
import { createDriveSession } from './driveOutline'
import { createOutlineStrip } from './driveOutlineWindow'
import {
  createDevTransport,
  createXpcTransport,
  loadXpcModule,
  type DevSpawn,
  type DriveTransport
} from './driveTransport'

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

/** The dev debug helper, only while it passes the helper path rule. */
function devHelper(): string | null {
  const helper = resolveDevHelper({
    appPath: app.getAppPath(),
    exists: existsSync,
    realpath: realLocalStateDeps.realpath
  })
  return helper !== null && isSafeHelperPath(helper, realHelperFs) ? helper : null
}

/** packaged — SolusInput.app's helper, the LaunchAgents plist and the XPC
 *  module are in the bundle; dev — the debug helper resolves and passes the
 *  helper path rule. */
function installed(): boolean {
  if (!app.isPackaged) return devHelper() !== null
  const files = packagedDriveFiles(process.resourcesPath)
  return [files.helper, files.plist, files.xpcModule].every(isPlainFile)
}

/** The transport, created on first use. Packaged: the native module from the
 *  app bundle — a module that fails to load leaves null (⇒ agent_unavailable). */
function createTransportSource(): () => DriveTransport | null {
  if (!app.isPackaged) {
    const transport = createDevTransport({
      helper: devHelper,
      spawn: ((command, args, options) => spawn(command, args, options)) as DevSpawn,
      warn,
      setTimeout: (cb, ms) => setTimeout(cb, ms),
      clearTimeout: (handle) => clearTimeout(handle as NodeJS.Timeout)
    })
    return () => transport
  }
  let loaded: DriveTransport | null | undefined
  return () => {
    if (loaded !== undefined) return loaded
    const module = loadXpcModule(
      () => createRequire(__filename)(packagedDriveFiles(process.resourcesPath).xpcModule),
      warn
    )
    loaded = module === null ? null : createXpcTransport(module)
    return loaded
  }
}

async function trustVia(
  transport: DriveTransport | null,
  prompt: boolean
): Promise<DriveTrustResult | null> {
  if (transport === null) return null
  const reply = await transport.request({ op: 'trust', prompt }, new AbortController().signal)
  return reply === null ? null : parseTrustOutput(JSON.stringify(reply))
}

export function startDrive(opts: {
  ipc: SolWindowIpc
  settings: SolSettings
  windows: Pick<SolWindowManager, 'broadcast'>
  isAllowedSender: (event: IpcMainInvokeEvent) => boolean
  /** The main renderer only — consent actions (drive on, `trust --prompt`, approval pane). */
  isMainSender: (event: IpcMainInvokeEvent) => boolean
}): DriveHandle {
  const transport = createTransportSource()
  const session = createDriveSession({
    createStrip: createOutlineStrip,
    now: Date.now,
    setTimeout: (cb, ms) => setTimeout(cb, ms),
    clearTimeout: (handle) => clearTimeout(handle as NodeJS.Timeout)
  })
  const registration = createAgentRegistration(app as unknown as LoginItemsApi, warn)
  // Packaged only: in dev main runs the helper per call, nothing to register.
  const onAgentWanted = (wanted: boolean): void => {
    if (process.platform === 'darwin' && app.isPackaged) registration.apply(wanted)
  }
  const controller = createDriveController({
    platform: process.platform,
    installed,
    trust: (prompt) => trustVia(transport(), prompt),
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
  setCompanionDriveTransport(transport)
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
  // First evaluation: clears an agent registration a previous run left behind
  // while the setting is now off.
  controller.refresh()
  return {
    setProject: (projectId) => controller.setProject(projectId),
    refresh: () => controller.refresh(),
    isQuiet: () => session.isQuiet(),
    dispose: () => {
      onCompanionDriveWindow(null)
      setCompanionDriveTransport(null)
      session.dispose()
    }
  }
}
