// SOLUSDEV-311: the error-reporting surface shared by main, preload and the
// renderer (docs/architecture/desktop-error-handling.md). Pure data — importable
// from every process. The closed sets mirror `client.error` in
// packages/api/src/solus_api/routers/events.py; keep them in lockstep.

export const DIAG_CHANNELS = {
  /** renderer → main: one caught renderer error (validated, scrubbed in main). */
  report: 'diag:report',
  /** renderer → main: read-and-clear the prior session's crash marker. */
  takeCrashMarker: 'diag:take-crash-marker'
} as const

export const RENDERER_ORIGINS = ['render', 'window_error', 'unhandled_rejection'] as const
export const CRASH_ORIGINS = ['main_process', 'renderer_gone'] as const
export type RendererErrorOrigin = (typeof RENDERER_ORIGINS)[number]
export type CrashOrigin = (typeof CRASH_ORIGINS)[number]
export type ErrorOrigin = RendererErrorOrigin | CrashOrigin

export const ERROR_SURFACES = [
  'root',
  'home',
  'workspace',
  'bench',
  'sol',
  'store',
  'billing',
  'settings',
  'alert',
  'extension',
  'sol_window',
  'overlay',
  'ext_window',
  'main'
] as const
export type ErrorSurface = (typeof ERROR_SURFACES)[number]

export const ERROR_NAMES = [
  'Error',
  'TypeError',
  'ReferenceError',
  'RangeError',
  'SyntaxError',
  'ApiError',
  'other'
] as const
export type ErrorNameCategory = (typeof ERROR_NAMES)[number]

/** Bounds on what a renderer may hand main; longer fields are truncated. */
export const REPORT_LIMITS = {
  name: 64,
  message: 1_000,
  stack: 8_000,
  componentStack: 4_000
} as const

/** One caught renderer error, as the renderer sends it (untrusted in main). */
export interface RendererErrorReport {
  origin: RendererErrorOrigin
  surface: ErrorSurface
  name: string
  message: string
  stack?: string
  componentStack?: string
}

/** Main's answer: the fingerprint, whether this is its first sighting this
 *  session (only the first becomes a data event), and the app version. */
export interface ReportAck {
  fingerprint: string
  first: boolean
  appVersion: string
}

/** A prior session's crash, handed to the next renderer once. */
export interface PendingCrash {
  origin: CrashOrigin
  surface: ErrorSurface
  errorName: ErrorNameCategory
  fingerprint: string
  appVersion: string
}

export const isOneOf = <T extends string>(set: readonly T[], v: unknown): v is T =>
  typeof v === 'string' && (set as readonly string[]).includes(v)

/** The closed `error_name` category for an arbitrary Error.name. */
export function errorNameCategory(name: string): ErrorNameCategory {
  return isOneOf(ERROR_NAMES, name) && name !== 'other' ? name : 'other'
}
