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
