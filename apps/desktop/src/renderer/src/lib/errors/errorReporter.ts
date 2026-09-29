// SOLUSDEV-311: the renderer's one error sink — boundaries and the global
// window handlers both call `report`. It forwards to main (which scrubs, logs
// and sends to Sentry) and, on main's first-sighting ack, emits the
// `client.error` data event (API.md §2.13): categories and a hash only, never
// the message or stack. Dev builds also echo to the console so nothing is
// swallowed while developing. Never throws.
import {
  REPORT_INPUT_LIMITS,
  errorNameCategory,
  type ErrorOrigin,
  type ErrorSurface,
  type RendererErrorOrigin,
  type RendererErrorReport
} from '../../../../main/diagnostics/diagnostics.constants'
import type { DataEventInput } from '../api/resources.extensions'
import type { DiagnosticsBridge } from '../desktopBridge'

export const CLIENT_ERROR_EVENT = 'client.error'
export const EVENT_BUDGET = { windowMs: 60_000, maxEvents: 10 } as const

export interface ReportContext {
  origin: RendererErrorOrigin
  surface: ErrorSurface
  componentStack?: string
}

export interface ErrorReporterDeps {
  bridge: () => DiagnosticsBridge | null
  emitEvents: (events: readonly DataEventInput[]) => Promise<void>
  projectId: () => string | undefined
  isDev: boolean
  consoleError: (...args: unknown[]) => void
  now?: () => number
}

export interface ErrorReporter {
  report: (error: unknown, context: ReportContext) => void
  /** Emit the prior session's main/renderer crash, once. Call when signed in. */
  reportPendingCrash: () => Promise<void>
}

const clip = (s: string, max: number): string => (s.length > max ? s.slice(0, max) : s)

function toReport(error: unknown, context: ReportContext): RendererErrorReport {
  const base = { origin: context.origin, surface: context.surface }
  const componentStack = context.componentStack ? { componentStack: context.componentStack } : {}
  if (error instanceof Error) {
    return {
      ...base,
      name: clip(error.name || 'Error', REPORT_INPUT_LIMITS.name),
      message: clip(error.message, REPORT_INPUT_LIMITS.message),
      ...(error.stack ? { stack: clip(error.stack, REPORT_INPUT_LIMITS.stack) } : {}),
      ...componentStack
    }
  }
  const message = typeof error === 'string' ? error : `Non-Error value: ${typeof error}`
  return {
    ...base,
    name: 'Error',
    message: clip(message, REPORT_INPUT_LIMITS.message),
    ...componentStack
  }
}

interface EventFields {
  origin: ErrorOrigin
  surface: ErrorSurface
  errorName: string
  fingerprint: string
  appVersion: string
}

function toEvent(fields: EventFields, projectId: string | undefined): DataEventInput {
  return {
    event_type: CLIENT_ERROR_EVENT,
    ...(projectId === undefined ? {} : { project_id: projectId }),
    payload: {
      origin: fields.origin,
      surface: fields.surface,
      error_name: errorNameCategory(fields.errorName),
      fingerprint: fields.fingerprint,
      app_version: fields.appVersion
    }
  }
}

export function createErrorReporter(deps: ErrorReporterDeps): ErrorReporter {
  const now = deps.now ?? Date.now
  const seen = new WeakSet<object>()
  let sent: number[] = []

  const emit = (fields: EventFields): void => {
    const t = now()
    sent = sent.filter((at) => t - at < EVENT_BUDGET.windowMs)
    if (sent.length >= EVENT_BUDGET.maxEvents) return
    sent = [...sent, t]
    // Best-effort, like every client event: signed out (401) or offline drops it.
    deps.emitEvents([toEvent(fields, deps.projectId())]).catch(() => undefined)
  }

  const forward = async (report: RendererErrorReport): Promise<void> => {
    const ack = await deps.bridge()?.report(report)
    if (ack?.first) emit({ ...report, errorName: report.name, ...ack })
  }

  return {
    report(error, context) {
      try {
        if (typeof error === 'object' && error !== null) {
          if (seen.has(error)) return
          seen.add(error)
        }
        if (deps.isDev)
          deps.consoleError(`[solus] ${context.origin} error in ${context.surface}`, error)
        void forward(toReport(error, context)).catch(() => undefined)
      } catch {
        // The reporter is the last line of defence; it must not become a fault.
      }
    },
    async reportPendingCrash() {
      try {
        const crash = await deps.bridge()?.takeCrashMarker()
        if (crash) emit(crash)
      } catch {
        // Same posture: losing one crash event is better than a new fault.
      }
    }
  }
}
