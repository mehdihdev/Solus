// SOLUSDEV-311: validate a `diag:report` payload. Any app window's renderer can
// send one, so it is untrusted: wrong shapes or extra keys are refused (null),
// oversize text is truncated rather than refused so a real error still lands.
import {
  ERROR_SURFACES,
  REPORT_LIMITS,
  RENDERER_ORIGINS,
  isOneOf,
  type RendererErrorReport
} from './diagnostics.constants'

const ALLOWED_KEYS = new Set(['origin', 'surface', 'name', 'message', 'stack', 'componentStack'])

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

const optionalString = (v: unknown): boolean => v === undefined || typeof v === 'string'

const clip = (s: string, max: number): string => (s.length > max ? s.slice(0, max) : s)

type ShapedReport = Record<string, unknown> &
  Pick<RendererErrorReport, 'origin' | 'surface' | 'name' | 'message'>

function hasValidShape(raw: Record<string, unknown>): raw is ShapedReport {
  return (
    isOneOf(RENDERER_ORIGINS, raw.origin) &&
    isOneOf(ERROR_SURFACES, raw.surface) &&
    typeof raw.name === 'string' &&
    typeof raw.message === 'string' &&
    optionalString(raw.stack) &&
    optionalString(raw.componentStack)
  )
}

export function parseRendererReport(raw: unknown): RendererErrorReport | null {
  if (!isRecord(raw) || Object.keys(raw).some((k) => !ALLOWED_KEYS.has(k))) return null
  if (!hasValidShape(raw)) return null
  const { origin, surface, name, message, stack, componentStack } = raw
  return {
    origin,
    surface,
    name: clip(name, REPORT_LIMITS.name),
    message: clip(message, REPORT_LIMITS.message),
    ...(typeof stack === 'string' ? { stack: clip(stack, REPORT_LIMITS.stack) } : {}),
    ...(typeof componentStack === 'string'
      ? { componentStack: clip(componentStack, REPORT_LIMITS.componentStack) }
      : {})
  }
}
