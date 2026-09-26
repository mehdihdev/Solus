// SOLUSDEV-311: the one scrubber every error report passes before it is logged
// or sent to Sentry (docs/architecture/desktop-error-handling.md §Privacy).
// Pure: text in, text out. Order matters — whole-token patterns run before the
// URL rule so a token inside a query string is redacted either way.
import { REPORT_LIMITS, type RendererErrorReport } from './diagnostics.constants'

const RULES: ReadonlyArray<readonly [RegExp, string]> = [
  [/\beyJ[\w-]+\.[\w-]+\.[\w-]+/g, '[jwt]'],
  [/\b(Bearer)\s+[^\s'"]+/gi, '$1 [redacted]'],
  [/\b(?:sk|pk|rk)_(?:live|test)_\w+/g, '[secret]'],
  [/\bsb_(?:secret|publishable)_\w+/g, '[secret]'],
  [/\bgh[pousr]_\w{20,}/g, '[secret]'],
  [/\bglpat-[\w-]{20,}/g, '[secret]'],
  [/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g, '[email]'],
  // Query strings: everything after `?` up to whitespace/quote.
  [/(\b[a-z][\w+.-]*:\/\/[^\s?'"]*)\?[^\s'"]*/gi, '$1?[redacted]'],
  // A second `#` after a hash route (`/#/login#access_token=…`), or a `#` that
  // is not a hash route at all.
  [/(\b[a-z][\w+.-]*:\/\/[^\s#'"]*(?:#\/[^\s#'"]*)?)#(?!\/)[^\s'"]+/gi, '$1#[redacted]'],
  [/\/Users\/[^/\s'"]+/g, '~'],
  [/\/home\/[^/\s'"]+/g, '~'],
  [/[A-Za-z]:\\Users\\[^\\\s'"]+/g, '~']
]

/** Redact credentials, emails, URL queries/fragments and user home paths. */
export function scrubText(text: string, homeDir: string): string {
  const home = homeDir && homeDir.length > 1 ? text.split(homeDir).join('~') : text
  return RULES.reduce((acc, [pattern, replacement]) => acc.replace(pattern, replacement), home)
}

const clip = (s: string, max: number): string => (s.length > max ? s.slice(0, max) : s)

/** A new report with every free-text field scrubbed and bounded. */
export function scrubReport(report: RendererErrorReport, homeDir: string): RendererErrorReport {
  const text = (s: string, max: number): string => clip(scrubText(s, homeDir), max)
  return {
    origin: report.origin,
    surface: report.surface,
    name: text(report.name, REPORT_LIMITS.name),
    message: text(report.message, REPORT_LIMITS.message),
    ...(report.stack === undefined ? {} : { stack: text(report.stack, REPORT_LIMITS.stack) }),
    ...(report.componentStack === undefined
      ? {}
      : { componentStack: text(report.componentStack, REPORT_LIMITS.componentStack) })
  }
}
