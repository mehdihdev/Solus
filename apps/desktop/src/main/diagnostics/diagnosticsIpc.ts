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

export interface DiagnosticsIpcDeps {
  diagnostics: { report: (input: DiagnosticInput) => ReportAck }
  marker: { take: () => PendingCrash | null }
  isAppSender: (sender: unknown) => boolean
  isMainSender: (sender: unknown) => boolean
}

export interface DiagnosticsIpc {
  report: (sender: unknown, raw: unknown) => ReportAck | null
  takeCrashMarker: (sender: unknown) => PendingCrash | null
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
    report: (sender, raw) => {
      if (!deps.isAppSender(sender)) return null
      const report = parseRendererReport(raw)
      return report ? deps.diagnostics.report(report) : null
    },
    takeCrashMarker: (sender) => (deps.isMainSender(sender) ? deps.marker.take() : null)
  }
}
