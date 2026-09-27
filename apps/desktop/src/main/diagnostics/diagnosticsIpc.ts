// SOLUSDEV-311: the two diagnostics IPC handlers, deps-injected so the sender
// gating is testable (index.ts binds the real windows). Every Solus window
// loads the same renderer bundle on a known hash route, so both "is this our
// renderer?" and "which surface is it?" are read from the sender's URL.
import { parseRendererReport } from './reportInput'
import type {
  DiagnosticInput,
  ErrorSurface,
  PendingCrash,
  ReportAck
} from './diagnostics.constants'

/** The slice of an IpcMainInvokeEvent the gates read. */
export interface IpcEventLike {
  sender: unknown
  senderFrame?: unknown
}

export interface DiagnosticsIpcDeps {
  diagnostics: {
    report: (input: DiagnosticInput) => ReportAck
    setConsent: (consent: boolean) => void
  }
  marker: { take: () => PendingCrash | null }
  isAppSender: (event: IpcEventLike) => boolean
  isMainSender: (event: IpcEventLike) => boolean
  /** The sender window's own surface, from its URL ('root' = the main window). */
  surfaceOf: (event: IpcEventLike) => ErrorSurface
}

export interface DiagnosticsIpc {
  report: (event: IpcEventLike, raw: unknown) => ReportAck | null
  takeCrashMarker: (event: IpcEventLike) => PendingCrash | null
  setConsent: (event: IpcEventLike, raw: unknown) => boolean
}

/** True when `url` is the app renderer at `rendererBase` (dev origin or the
 *  packaged index.html) — exact match, then only a path/hash may follow. */
export function isAppRendererUrl(url: string, rendererBase: string): boolean {
  if (!url || !rendererBase) return false
  const base = rendererBase.replace(/\/$/, '')
  if (!url.startsWith(base)) return false
  const next = url.charAt(base.length)
  return next === '' || next === '/' || next === '#' || next === '?'
}

const HASH_SURFACES: ReadonlyArray<readonly [string, ErrorSurface]> = [
  ['#/sol-window', 'sol_window'],
  ['#/overlay', 'overlay'],
  ['#/ext-window', 'ext_window']
]

export function surfaceForUrl(url: string): ErrorSurface {
  const hash = url.slice(url.indexOf('#'))
  const match = url.includes('#')
    ? HASH_SURFACES.find(([prefix]) => hash.startsWith(prefix))
    : undefined
  return match ? match[1] : 'root'
}

export function createDiagnosticsIpc(deps: DiagnosticsIpcDeps): DiagnosticsIpc {
  return {
    report: (event, raw) => {
      if (!deps.isAppSender(event)) return null
      const report = parseRendererReport(raw)
      if (!report) return null
      // A secondary window cannot label its errors as another surface's.
      const own = deps.surfaceOf(event)
      return deps.diagnostics.report(own === 'root' ? report : { ...report, surface: own })
    },
    takeCrashMarker: (event) => (deps.isMainSender(event) ? deps.marker.take() : null),
    setConsent: (event, raw) => {
      if (!deps.isMainSender(event) || typeof raw !== 'boolean') return false
      deps.diagnostics.setConsent(raw)
      return true
    }
  }
}
