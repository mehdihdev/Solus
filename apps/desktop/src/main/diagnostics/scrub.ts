// SOLUSDEV-311: the one scrubber every error report passes before it is logged
// or sent to Sentry (docs/architecture/desktop-error-handling.md §Privacy).
// Pure: text in, text out. Order matters — whole-token patterns first, then
// URLs (so a query string goes whole), then credential-named values, then paths.
import { REPORT_LIMITS, type DiagnosticInput } from './diagnostics.constants'

/** Keys whose value is a credential wherever it appears (`key=v`, `"key":"v"`, `key: 'v'`).
 *  Not `code` — `code=ECONNREFUSED` is the diagnostic, not a secret. */
const SECRET_KEYS =
  'refresh_token|access_token|id_token|client_secret|password|passwd|secret|api[_-]?key|apikey'

const RULES: ReadonlyArray<readonly [RegExp, string]> = [
  // Tokens — also partial (a JWT cut mid-payload) and glued to a word (`x_eyJ…`).
  [/eyJ[\w-]{4,}(?:\.[\w-]*){0,2}/g, '[jwt]'],
  [/\b(Bearer)\s+[^\s'"]+/gi, '$1 [redacted]'],
  [/\b(Basic)\s+[A-Za-z0-9+/=]{8,}/g, '$1 [redacted]'],
  [/\b(?:sk|pk|rk)_(?:live|test)_\w+/g, '[secret]'],
  [/\bwhsec_\w+/g, '[secret]'],
  [/\bsb_(?:secret|publishable)_[\w-]+/g, '[secret]'],
  [/\b(?:gh[pousr]_\w{20,}|github_pat_\w{20,})/g, '[secret]'],
  [/\bgl(?:pat|dt|rt|oas|ptt|soat|cbt|imt)-[\w-]{20,}/g, '[secret]'],
  [/\bsk-(?:ant|proj)-[\w-]{10,}/g, '[secret]'],
  [/\b(?:AKIA|ASIA)[0-9A-Z]{16}\b/g, '[secret]'],
  [/[\w.+-]+(?:@|%40)[\w-]+(?:\.[\w-]+)+/g, '[email]'],
  // URLs: query strings, then a second `#` after a hash route (or a `#` that is
  // not a route) — absolute first, then schemeless/relative.
  [/(\b[a-z][\w+.-]*:\/\/[^\s?'"]*)\?[^\s'"]*/gi, '$1?[redacted]'],
  [/(\b[a-z][\w+.-]*:\/\/[^\s#'"]*(?:#\/[^\s#'"]*)?)#(?!\/)[^\s'"]+/gi, '$1#[redacted]'],
  [/(^|[\s('"=])(\/[^\s?#'"]*)\?[^\s'"]*/g, '$1$2?[redacted]'],
  [/(#\/[^\s#'"]*)#(?!\/)[^\s'"]+/g, '$1#[redacted]'],
  // Credential-named values, after the URL rules so a query is redacted whole.
  [new RegExp(`(["']?(?:${SECRET_KEYS})["']?\\s*[:=]\\s*["']?)[^\\s"'&,}]+`, 'gi'), '$1[redacted]'],
  // Home directories, plain, percent-encoded and JSON-escaped.
  [/\/Users\/[^/\s'"]+/g, '~'],
  [/\/home\/[^/\s'"]+/g, '~'],
  [/(^|[\s('"=])\/root(?=\/)/g, '$1~'],
  [/%2FUsers%2F[^%\s'"&]+/gi, '~'],
  [/[A-Za-z]:\\{1,2}Users\\{1,2}[^\\\s'"]+/g, '~']
]

/** Redact credentials, emails, URL queries/fragments and user home paths. */
export function scrubText(text: string, homeDir: string): string {
  const home = homeDir && homeDir.length > 1 ? text.split(homeDir).join('~') : text
  return RULES.reduce((acc, [pattern, replacement]) => acc.replace(pattern, replacement), home)
}

const clip = (s: string, max: number): string => (s.length > max ? s.slice(0, max) : s)

/** A new report with every free-text field scrubbed and bounded. */
export function scrubReport<T extends DiagnosticInput>(report: T, homeDir: string): T {
  const text = (s: string, max: number): string => clip(scrubText(s, homeDir), max)
  return {
    ...report,
    name: text(report.name, REPORT_LIMITS.name),
    message: text(report.message, REPORT_LIMITS.message),
    ...(report.stack === undefined ? {} : { stack: text(report.stack, REPORT_LIMITS.stack) }),
    ...(report.componentStack === undefined
      ? {}
      : { componentStack: text(report.componentStack, REPORT_LIMITS.componentStack) })
  }
}
