// Pure presentation helpers for connected sources (SOLUSDEV-164). Kept side by
// side with the project screens and free of React so both the overview and the
// Sources page render source status/type identically (DRY). Colors resolve to
// theme tokens (apps/desktop CLAUDE.md — no hardcoded colors).
import type { SourceError, SourceStatus } from '../../lib/api/resources'

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
const ERROR_TEXT_MAX = 500

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
