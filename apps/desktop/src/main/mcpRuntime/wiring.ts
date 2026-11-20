// SOLUSDEV-329 — binds the mcpRuntime:* handlers to Electron and node
// (docs/architecture/mcp-fork-runtime.md §9). Glue only: every decision is in
// ipc.ts / runtimeCli.ts / probe.ts / runtimeSettings.ts, tested there.
import { app, dialog, type BrowserWindow, type IpcMainInvokeEvent } from 'electron'
import { execFile, spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { existsSync, statSync } from 'node:fs'
import { promisify } from 'node:util'
import { killTree, resolveCompanionCommand, respawnCompanion } from '../companion'
import { findIntegrationsRoot, runtimeCliEnv } from '../companionEnv'
import { realLocalStateDeps } from '../localState'
import { createMcpRuntimeIpc, registerMcpRuntimeIpc, type IpcMainLike } from './ipc'
import { probeInterpreter } from './probe'
import { createRuntimeSettings } from './runtimeSettings'

const execFileAsync = promisify(execFile)

export interface McpRuntimeWiring {
  ipcMain: IpcMainLike
  isAllowed: (event: IpcMainInvokeEvent) => boolean
  window: () => BrowserWindow | null
}

async function pickInterpreter(window: BrowserWindow | null): Promise<string | null> {
  if (window === null) return null
  const picked = await dialog.showOpenDialog(window, {
    title: 'Choose a Python 3.12 or 3.13 interpreter',
    properties: ['openFile', 'dontAddToRecent', 'treatPackageAsDirectory'],
    ...(process.platform === 'win32' ? { filters: [{ name: 'Python', extensions: ['exe'] }] } : {})
  })
  return picked.canceled || picked.filePaths.length !== 1 ? null : picked.filePaths[0]
}

/** Main's own confirmation before the managed download (security LOW-3). */
async function confirmManagedDownload(window: BrowserWindow | null): Promise<boolean> {
  if (window === null) return false
  const { response } = await dialog.showMessageBox(window, {
    type: 'question',
    buttons: ['Download', 'Cancel'],
    defaultId: 0,
    cancelId: 1,
    message: 'Download Python for Solus?',
    detail:
      'Solus will download CPython 3.12 from python-build-standalone (about 30 MB) into its app-data folder. Nothing else on your computer changes.'
  })
  return response === 0
}

const isFile = (path: string): boolean => {
  try {
    return statSync(path).isFile()
  } catch {
    return false
  }
}

export function registerMcpRuntime(wiring: McpRuntimeWiring): void {
  const ipc = createMcpRuntimeIpc({
    isAllowed: (event) => wiring.isAllowed(event as unknown as IpcMainInvokeEvent),
    commandLine: () =>
      resolveCompanionCommand({
        isPackaged: app.isPackaged,
        resourcesPath: process.resourcesPath,
        platform: process.platform,
        env: process.env
      }),
    env: () =>
      runtimeCliEnv(
        process.env,
        app.isPackaged,
        app.isPackaged ? null : findIntegrationsRoot(app.getAppPath(), existsSync)
      ),
    run: { spawn: (command, args, options) => spawn(command, args, options), kill: killTree },
    settings: createRuntimeSettings(realLocalStateDeps),
    probe: (path) =>
      probeInterpreter(path, {
        execFile: (file, args, options) =>
          execFileAsync(file, args, { ...options, encoding: 'utf8' }),
        realpath: realLocalStateDeps.realpath,
        isFile
      }),
    pickInterpreter: () => pickInterpreter(wiring.window()),
    realpath: realLocalStateDeps.realpath,
    confirmManagedDownload: () => confirmManagedDownload(wiring.window()),
    respawnCompanion,
    newRunId: randomUUID
  })
  registerMcpRuntimeIpc(wiring.ipcMain, ipc)
}
