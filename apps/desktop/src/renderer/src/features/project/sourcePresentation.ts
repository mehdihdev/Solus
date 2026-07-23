// Pure presentation helpers for connected sources (SOLUSDEV-164). Kept side by
// side with the project screens and free of React so both the overview and the
// Sources page render source status/type identically (DRY). Colors resolve to
// theme tokens (apps/desktop CLAUDE.md — no hardcoded colors).
import type { SourceStatus } from '../../lib/api/resources'

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
