// SOLUSDEV-311: main-process crash supervision (human decision: report, then
// relaunch). Installed first thing in main so nothing escapes it.
// - uncaughtException: report → mark for the next renderer → flush Sentry →
//   relaunch, at most once per RELAUNCH_WINDOW_MS; a repeat quits with a dialog
//   so a crash-on-boot cannot loop. Dev reports and exits (electron-vite owns
//   the process — a relaunch would orphan it). Re-entrant throws exit at once.
// - unhandledRejection: report only; main keeps running (Electron's default).
// - render-process-gone (not a clean exit): report and mark.
import {
  errorNameCategory,
  type DiagnosticInput,
  type ErrorSurface,
  type ReportAck
} from './diagnostics.constants'
import type { CrashMarker } from './crashMarker'

const FLUSH_TIMEOUT_MS = 2_000

export const CRASH_DIALOG = {
  title: 'Solus stopped',
  body:
    'Solus hit an unexpected problem twice in a row and closed to protect your work. ' +
    'Please restart Solus. If it keeps happening, the details are in solus-errors.log in the Solus logs folder.'
} as const

interface RenderGoneDetails {
  reason?: string
  exitCode?: number
}

export interface CrashHandlerDeps {
  proc: {
    on: (event: 'uncaughtException' | 'unhandledRejection', fn: (reason: unknown) => void) => void
  }
  app: {
    on: (
      event: 'render-process-gone',
      fn: (event: unknown, contents: unknown, details: RenderGoneDetails) => void
    ) => void
    relaunch: () => void
    exit: (code: number) => void
  }
  diagnostics: {
    report: (input: DiagnosticInput) => ReportAck
    flush: (ms: number) => Promise<void>
  }
  marker: Pick<CrashMarker, 'record' | 'mayRelaunch' | 'markRelaunch'>
  showErrorBox: (title: string, body: string) => void
  now: () => number
  isDev: boolean
  surfaceFor: (contents: unknown) => ErrorSurface
  /** Test seam: observe the async tail of a crash. */
  track?: (pending: Promise<unknown>) => void
}

function describe(reason: unknown): Pick<DiagnosticInput, 'name' | 'message' | 'stack'> {
  if (reason instanceof Error)
    return { name: reason.name, message: reason.message, stack: reason.stack }
  return { name: 'Error', message: typeof reason === 'string' ? reason : 'non-Error value thrown' }
}

function reportAndMark(deps: CrashHandlerDeps, input: DiagnosticInput): void {
  const ack = deps.diagnostics.report(input)
  if (input.origin !== 'main_process' && input.origin !== 'renderer_gone') return
  deps.marker.record({
    origin: input.origin,
    surface: input.surface,
    errorName: errorNameCategory(input.name),
    fingerprint: ack.fingerprint,
    appVersion: ack.appVersion
  })
}

async function stopAfterCrash(deps: CrashHandlerDeps): Promise<void> {
  // Relaunch only once the guard is on disk: an unsaved guard cannot stop a loop.
  const relaunch =
    !deps.isDev && deps.marker.mayRelaunch(deps.now()) && deps.marker.markRelaunch(deps.now())
  await deps.diagnostics.flush(FLUSH_TIMEOUT_MS).catch(() => undefined)
  if (relaunch) deps.app.relaunch()
  else if (!deps.isDev) deps.showErrorBox(CRASH_DIALOG.title, CRASH_DIALOG.body)
  deps.app.exit(1)
}

export function installCrashHandlers(deps: CrashHandlerDeps): void {
  let handling = false
  deps.proc.on('uncaughtException', (reason) => {
    if (handling) {
      deps.app.exit(1)
      return
    }
    handling = true
    try {
      reportAndMark(deps, { origin: 'main_process', surface: 'main', ...describe(reason) })
    } catch {
      // Reporting must never block the exit path.
    }
    const tail = stopAfterCrash(deps)
    deps.track?.(tail)
  })
  deps.proc.on('unhandledRejection', (reason) => {
    deps.diagnostics.report({ origin: 'main_process', surface: 'main', ...describe(reason) })
  })
  deps.app.on('render-process-gone', (_event, contents, details) => {
    if (details.reason === 'clean-exit') return
    reportAndMark(deps, {
      origin: 'renderer_gone',
      surface: deps.surfaceFor(contents),
      name: 'RendererGone',
      message: `reason=${details.reason ?? 'unknown'} exitCode=${details.exitCode ?? 'unknown'}`
    })
  })
}
