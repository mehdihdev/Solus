// SOLUSDEV-329 — binds the mcpRuntime:* handlers to Electron and node
// (docs/architecture/mcp-fork-runtime.md §9). Glue only: every decision is in
// ipc.ts / runtimeCli.ts / probe.ts / runtimeSettings.ts, tested there.
import { app, dialog, type BrowserWindow, type IpcMainInvokeEvent } from 'electron'
import { execFile, spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { statSync } from 'node:fs'
import { promisify } from 'node:util'
import { killTree, resolveCompanionCommand, respawnCompanion } from '../companion'
import { runtimeCliEnv } from '../companionEnv'
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
    env: () => runtimeCliEnv(process.env, app.isPackaged),
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
    respawnCompanion,
    newRunId: randomUUID
  })
  registerMcpRuntimeIpc(wiring.ipcMain, ipc)
}
