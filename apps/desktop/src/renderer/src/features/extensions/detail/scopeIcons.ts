// SOLUSDEV-235 — one glyph per bridge scope, shared by the permissions step and
// the Permissions tab. Keyed by the contract's closed set, so a new scope is a
// compile error here until it gets an icon.
import type { PermissionScope } from '@solus/shared-types'
import type { IconName } from '../../../components/ui/icons.constants'

export const SCOPE_ICON: Readonly<Record<PermissionScope, IconName>> = {
  'graph.read': 'hex',
  'telemetry.read': 'wave',
  'sources.read': 'link',
  'findings.write': 'triangle',
  'sol.ask': 'sol',
  'storage.own': 'box',
  'focus.read': 'search',
  'focus.write': 'spark'
}
