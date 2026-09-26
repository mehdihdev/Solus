// SOLUSDEV-311: wires the diagnostics pieces together for main/index.ts.
// Called at module load — before the single-instance lock and app ready — so
// a crash anywhere after it is reported. Electron is injected (index.ts binds
// the real modules) so the wiring is testable.
import { join } from 'node:path'
import { createCrashMarker, fileCrashMarkerIo, CRASH_MARKER_FILENAME } from './crashMarker'
import { installCrashHandlers, type CrashHandlerDeps } from './crashHandlers'
import { createDiagnostics } from './diagnostics'
import { createDiagnosticsIpc, surfaceForUrl } from './diagnosticsIpc'
import { DIAG_CHANNELS } from './diagnostics.constants'
import {
  createErrorLog,
  realErrorLogDeps,
  ERROR_LOG_FILENAME,
  ERROR_LOG_MAX_BYTES
} from './errorLog'
import type { loadSentrySink } from './sentrySink'

export interface SentryConfig {
  dsn: string | undefined
  environment: string
}

export interface BootDeps {
  app: CrashHandlerDeps['app'] & {
    getPath: (name: 'logs' | 'userData') => string
    getVersion: () => string
  }
  proc: CrashHandlerDeps['proc']
  ipcMain: {
    handle: (
      channel: string,
      fn: (event: { sender: unknown }, ...args: unknown[]) => unknown
    ) => void
  }
  showErrorBox: (title: string, body: string) => void
  homeDir: string
  isDev: boolean
  ensureDir: (path: string) => void
  loadSentry: typeof loadSentrySink
  sentry: SentryConfig
}

export interface SenderGates {
  isAppSender: (sender: unknown) => boolean
  isMainSender: (sender: unknown) => boolean
}

export interface BootedDiagnostics {
  registerIpc: (gates: SenderGates) => void
}

/** The DSN from the runtime env (`SENTRY_DSN`) or the build-time root `.env`
 *  (`MAIN_VITE_SENTRY_DSN`, inlined so packaged builds have it). */
export function resolveSentryConfig(
  runtime: { readonly [key: string]: string | undefined; readonly SENTRY_DSN?: string },
  build: { readonly MAIN_VITE_SENTRY_DSN?: string; readonly MAIN_VITE_SENTRY_ENVIRONMENT?: string },
  isDev: boolean
): SentryConfig {
  const dsn = runtime.SENTRY_DSN?.trim() || build.MAIN_VITE_SENTRY_DSN?.trim() || undefined
  const environment =
    build.MAIN_VITE_SENTRY_ENVIRONMENT?.trim() || (isDev ? 'development' : 'production')
  return { dsn, environment }
}

function urlOf(contents: unknown): string {
  const getURL = (contents as { getURL?: () => string } | null)?.getURL
  return typeof getURL === 'function' ? getURL.call(contents) : ''
}

export function bootDiagnostics(deps: BootDeps): BootedDiagnostics {
  const logDir = deps.app.getPath('logs')
  try {
    deps.ensureDir(logDir)
  } catch {
    // The log write reports its own failure on stderr.
  }
  const appVersion = deps.app.getVersion()
  const log = createErrorLog({
    path: join(logDir, ERROR_LOG_FILENAME),
    maxBytes: ERROR_LOG_MAX_BYTES,
    deps: realErrorLogDeps
  })
  const diagnostics = createDiagnostics({ homeDir: deps.homeDir, appVersion, log })
  const marker = createCrashMarker(
    fileCrashMarkerIo(join(deps.app.getPath('userData'), CRASH_MARKER_FILENAME))
  )
  installCrashHandlers({
    proc: deps.proc,
    app: deps.app,
    diagnostics,
    marker,
    showErrorBox: deps.showErrorBox,
    now: Date.now,
    isDev: deps.isDev,
    surfaceFor: (contents) => surfaceForUrl(urlOf(contents))
  })
  void deps
    .loadSentry({ ...deps.sentry, release: `solus-desktop@${appVersion}`, homeDir: deps.homeDir })
    .then((sink) => diagnostics.setSentry(sink))
  return {
    registerIpc: (gates) => {
      const ipc = createDiagnosticsIpc({ diagnostics, marker, ...gates })
      deps.ipcMain.handle(DIAG_CHANNELS.report, (event, raw) => ipc.report(event.sender, raw))
      deps.ipcMain.handle(DIAG_CHANNELS.takeCrashMarker, (event) =>
        ipc.takeCrashMarker(event.sender)
      )
    }
  }
}
