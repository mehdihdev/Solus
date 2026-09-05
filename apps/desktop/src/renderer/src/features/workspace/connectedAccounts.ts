// Copy helpers for Home's connected-accounts card (SOLUSDEV-241). Pure, so the
// card file exports only components (fast refresh) and the words are testable
// without rendering.
import type { Connection } from '../../lib/api/resources'

/** "Used in Rover and Arm" / "Used in 3 projects" / "Not used by any project yet". */
export function usageText(connection: Connection): string {
  const names = connection.projects.map((p) => p.name)
  if (names.length === 0) return 'Not used by any project yet'
  if (names.length <= 2) return `Used in ${names.join(' and ')}`
  return `Used in ${names.length} projects`
}

/** What the grant lets Solus do, stated plainly on every row (SOLUSDEV-242 / H2). */
export function scopeText(connection: Connection): string {
  if (connection.access === 'write') return 'Read and edit'
  if (connection.access === 'read') return 'Read only'
  return 'Access level not recorded'
}

/** Why the row asks for a fresh sign-in, or null. Never forces it: the
 *  existing token keeps working until the new consent succeeds. */
export function reauthText(connection: Connection): string | null {
  if (connection.needs_reauth === 'access_unknown') {
    return (
      'Linked from a project before account-level connections; what Solus may do with it ' +
      'was never recorded. Re-authorize to confirm — existing syncs keep working until then.'
    )
  }
  if (connection.needs_reauth === 'token_error' || connection.status === 'error') {
    return connection.last_error?.message
      ? `${connection.last_error.message} Re-authorize to reconnect.`
      : 'The last sign-in failed. Re-authorize to reconnect.'
  }
  return null
}

/** The confirmation must say what revoking disconnects. */
export function revokeDetail(providerName: string, connection: Connection): string {
  const names = connection.projects.map((p) => p.name)
  if (names.length === 0) {
    return `Solus loses access to this ${providerName} account. No project uses it right now.`
  }
  const where = names.length <= 3 ? names.join(', ') : `${names.length} projects`
  return (
    `Solus loses access to this ${providerName} account and disconnects ${providerName} in ` +
    `${where}. The entities those projects already synced stay in their graphs.`
  )
}
