// SOLUSDEV-311: the renderer end of error reporting, exposed as
// window.solus.diagnostics. A pure factory over an injected ipcRenderer (the
// solBridge pattern). Never rejects: reporting an error must not throw.
import {
  CRASH_ORIGINS,
  DIAG_CHANNELS,
  ERROR_NAMES,
  ERROR_SURFACES,
  isOneOf,
  type PendingCrash,
  type RendererErrorReport,
  type ReportAck
} from '../main/diagnostics/diagnostics.constants'

export interface DiagnosticsBridgeIpc {
  invoke(channel: string, ...args: unknown[]): Promise<unknown>
}

export interface DiagnosticsBridge {
  report(report: RendererErrorReport): Promise<ReportAck | null>
  takeCrashMarker(): Promise<PendingCrash | null>
}

const FINGERPRINT = /^[0-9a-f]{16}$/

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

const isAck = (v: unknown): v is ReportAck =>
  isRecord(v) &&
  typeof v.fingerprint === 'string' &&
  FINGERPRINT.test(v.fingerprint) &&
  typeof v.first === 'boolean' &&
  typeof v.appVersion === 'string'

const isPendingCrash = (v: unknown): v is PendingCrash =>
  isRecord(v) &&
  isOneOf(CRASH_ORIGINS, v.origin) &&
  isOneOf(ERROR_SURFACES, v.surface) &&
  isOneOf(ERROR_NAMES, v.errorName) &&
  typeof v.fingerprint === 'string' &&
  FINGERPRINT.test(v.fingerprint) &&
  typeof v.appVersion === 'string'

async function safeInvoke<T>(
  ipc: DiagnosticsBridgeIpc,
  guard: (v: unknown) => v is T,
  channel: string,
  ...args: unknown[]
): Promise<T | null> {
  try {
    const answer = await ipc.invoke(channel, ...args)
    return guard(answer) ? answer : null
  } catch {
    return null
  }
}

export function createDiagnosticsBridge(ipc: DiagnosticsBridgeIpc): DiagnosticsBridge {
  return {
    report: (report) => safeInvoke(ipc, isAck, DIAG_CHANNELS.report, report),
    takeCrashMarker: () => safeInvoke(ipc, isPendingCrash, DIAG_CHANNELS.takeCrashMarker)
  }
}
