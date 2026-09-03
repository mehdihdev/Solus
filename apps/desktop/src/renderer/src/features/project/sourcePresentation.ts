// Pure presentation helpers for connected sources (SOLUSDEV-164). Kept side by
// side with the project screens and free of React so both the overview and the
// Sources page render source status/type identically (DRY). Colors resolve to
// theme tokens (apps/desktop CLAUDE.md — no hardcoded colors).
import type { HostedState, Source, SourceError, SourceStatus } from '../../lib/api/resources'

const STATUS_COLOR: Readonly<Record<SourceStatus, string>> = {
  connected: 'var(--ok)',
  syncing: 'var(--acc)',
  pending: 'var(--mut)',
  error: 'var(--err)',
  disconnected: 'var(--mut)'
}

/** Theme-token color for a source's status dot/pill. */
export function sourceStatusColor(status: SourceStatus): string {
  return STATUS_COLOR[status] ?? 'var(--mut)'
}

const TYPE_LABEL: Readonly<Record<string, string>> = {
  github: 'GitHub · Code',
  gitlab: 'GitLab · Code',
  kicad: 'KiCad · PCB / Schematic',
  altium: 'Altium · PCB / Schematic',
  onshape: 'Onshape · CAD',
  ros: 'ROS · Runtime'
}

/** Human label for a connector type, capitalizing unknown types as a fallback. */
export function sourceTypeLabel(type: string): string {
  return TYPE_LABEL[type] ?? type.charAt(0).toUpperCase() + type.slice(1)
}

/** Belt-and-braces render cap — the API bounds messages at write, but a stale
 * or hostile payload must still never dump unbounded text into a row. */
export const ERROR_TEXT_MAX = 500

/**
 * Renderable text for a source's last error, or null when there is none.
 * The API serializes `last_error` as a structured `{code, message}` object
 * (SOLUSDEV-114 — rendering the raw object crashed the app); anything
 * malformed degrades to null, never to a non-string React child, and the
 * result is length-capped. The plain-string branch has no typed caller today
 * (`Source.last_error` is object|null) — pure defense against legacy payloads.
 */
export function sourceErrorText(error: SourceError | string | null): string | null {
  if (!error) return null
  if (typeof error === 'string') return error.slice(0, ERROR_TEXT_MAX)
  if (typeof error !== 'object') return null
  const message = typeof error.message === 'string' ? error.message : ''
  const code = typeof error.code === 'string' ? error.code : ''
  const text = message || code
  return text ? text.slice(0, ERROR_TEXT_MAX) : null
}


/** The hosted add-on entry the API echoes back for one source, or undefined.
 *
 *  `serialize_source` strips underscore-prefixed config keys, so `hosted` — the
 *  customer-visible state — is present while `_hosted`, the vetted descriptor
 *  set the registry replays, is not. That split is deliberate: server-authored
 *  schemas are not something any API response should hand back out.
 */
function hostedEntry(source: Source, server: string): Record<string, unknown> | undefined {
  const hosted = (source.config as Record<string, unknown> | undefined)?.hosted
  if (!hosted || typeof hosted !== 'object') return undefined
  const entry = (hosted as Record<string, unknown>)[server]
  return entry && typeof entry === 'object' ? (entry as Record<string, unknown>) : undefined
}

/**
 * A hosted add-on's state for one source.
 *
 * SERVER-BACKED by design: the connect wizard cancels its attempt on close and
 * the Sources screen resets the onboarding store on mount, so a
 * renderer-resident flag would be lost on every navigation and would be wrong
 * for every teammate who did not run the connect themselves. Absent or
 * malformed means the backend has never recorded a grant, which IS
 * `not_connected` — never an optimistic default.
 */
export function hostedState(source: Source, server: string): HostedState {
  const state = hostedEntry(source, server)?.state
  return state === 'ready' || state === 'subscription_required' ? state : 'not_connected'
}

/** The probe's own reason, in the vendor's words — capped like every other
 *  server-authored string this file renders. Null when there is nothing to say. */
export function hostedDetail(source: Source, server: string): string | null {
  const detail = hostedEntry(source, server)?.detail
  return typeof detail === 'string' && detail ? detail.slice(0, ERROR_TEXT_MAX) : null
}
