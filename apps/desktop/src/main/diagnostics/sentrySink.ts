// SOLUSDEV-311: Sentry, main process only (renderer reports reach it over our
// own validated IPC, so the renderer CSP never widens). Loaded lazily and only
// when a DSN is configured. Privacy posture (CLAUDE.md §7 — no PII or tokens):
// sendDefaultPii off, breadcrumbs dropped, integrations allowlisted (no
// minidumps — raw memory can hold tokens — no local variables, console/net/
// fetch capture, screenshots, sessions, or the SDK's own uncaught handlers,
// which crashHandlers.ts owns), and beforeSend re-scrubs as defence in depth.
// The SDK also registers renderer-facing `ipcMain` channels with no sender
// check; the preload exposes raw ipcRenderer, so any window could feed Sentry
// directly. They are torn down right after init (security review H1) and the
// namespace is random per launch. Main-side capture never uses them.
import { randomUUID } from 'node:crypto'
import { scrubText } from './scrub'
import type { DiagnosticInput } from './diagnostics.constants'
import type { SentrySink } from './diagnostics'

/** The slice of @sentry/electron/main this sink uses (a fake in tests). */
export interface SentryModule {
  init: (options: SentryInitOptions) => void
  captureException: (error: Error, hint: CaptureHint) => void
  flush: (timeoutMs: number) => Promise<boolean>
  IPCMode: { Classic: number }
}

interface Integration {
  name: string
}

interface SentryEventLike {
  message?: string
  exception?: { values?: Array<{ value?: string }> }
  [key: string]: unknown
}

interface SentryInitOptions {
  dsn: string
  ipcNamespace: string
  transportOptions: { flushAtStartup: false; shouldStore: () => false }
  release: string
  environment: string
  sendDefaultPii: false
  ipcMode: number
  skipOpenTelemetrySetup: true
  integrations: <T extends Integration>(defaults: T[]) => T[]
  beforeBreadcrumb: () => null
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- the SDK's Event type, narrowed inside
  beforeSend: (event: any) => any
}

interface CaptureHint {
  fingerprint: string[]
  tags: { origin: string; surface: string }
  contexts?: { react: { componentStack: string } }
}

/** Context and grouping only — nothing that captures data from the machine. */
export const KEPT_INTEGRATIONS: ReadonlySet<string> = new Set([
  'ElectronContext',
  'EventFilters',
  'FunctionToString',
  'LinkedErrors',
  'NormalizePaths'
])

/** The slice of ipcMain used to tear the SDK's renderer channels down. */
export interface SentryIpcTeardown {
  removeAllListeners: (channel: string) => void
  removeHandler: (channel: string) => void
}

/** Channels @sentry/electron's Classic IPC mode registers (`<ns>.<channel>`). */
const SDK_LISTENER_CHANNELS = ['start', 'scope', 'envelope', 'structured-log', 'metric', 'status']
const SDK_HANDLER_CHANNELS = ['feedback']

function closeSdkIpc(ipc: SentryIpcTeardown, namespace: string): void {
  SDK_LISTENER_CHANNELS.forEach((ch) => ipc.removeAllListeners(`${namespace}.${ch}`))
  SDK_HANDLER_CHANNELS.forEach((ch) => ipc.removeHandler(`${namespace}.${ch}`))
}

export interface SentrySinkOptions {
  dsn: string | undefined
  ipc: SentryIpcTeardown
  environment: string
  release: string
  homeDir: string
  load?: () => Promise<SentryModule>
}

const realLoad = async (): Promise<SentryModule> =>
  (await import('@sentry/electron/main')) as unknown as SentryModule

/** Event fields that identify the machine or the person; never sent. */
const DROPPED_EVENT_KEYS = new Set(['user', 'request', 'server_name'])

function scrubEvent(event: SentryEventLike, homeDir: string): SentryEventLike {
  const rest: SentryEventLike = Object.fromEntries(
    Object.entries(event).filter(([key]) => !DROPPED_EVENT_KEYS.has(key))
  )
  const values = rest.exception?.values?.map((v) => ({
    ...v,
    ...(v.value === undefined ? {} : { value: scrubText(v.value, homeDir) })
  }))
  return {
    ...rest,
    ...(rest.message === undefined ? {} : { message: scrubText(rest.message, homeDir) }),
    ...(values === undefined ? {} : { exception: { ...rest.exception, values } })
  }
}

function toError(report: DiagnosticInput): Error {
  const error = new Error(report.message)
  error.name = report.name
  error.stack = report.stack ?? `${report.name}: ${report.message}`
  return error
}

export async function loadSentrySink(options: SentrySinkOptions): Promise<SentrySink | null> {
  const dsn = options.dsn?.trim()
  if (!dsn) return null
  let sentry: SentryModule
  try {
    sentry = await (options.load ?? realLoad)()
  } catch {
    return null
  }
  const ipcNamespace = `sentry-ipc-${randomUUID()}`
  sentry.init({
    dsn,
    ipcNamespace,
    // No offline queue: a queued report would be flushed at the next startup,
    // before that session's consent is known (re-verification N2).
    transportOptions: { flushAtStartup: false, shouldStore: () => false },
    release: options.release,
    environment: options.environment,
    sendDefaultPii: false,
    ipcMode: sentry.IPCMode.Classic,
    skipOpenTelemetrySetup: true,
    integrations: (defaults) => defaults.filter((i) => KEPT_INTEGRATIONS.has(i.name)),
    beforeBreadcrumb: () => null,
    beforeSend: (event: SentryEventLike) => scrubEvent(event, options.homeDir)
  })
  closeSdkIpc(options.ipc, ipcNamespace)
  return {
    capture: (report) =>
      sentry.captureException(toError(report), {
        fingerprint: [report.fingerprint],
        tags: { origin: report.origin, surface: report.surface },
        ...(report.componentStack
          ? { contexts: { react: { componentStack: report.componentStack } } }
          : {})
      }),
    flush: async (timeoutMs) => {
      await sentry.flush(timeoutMs)
    }
  }
}
