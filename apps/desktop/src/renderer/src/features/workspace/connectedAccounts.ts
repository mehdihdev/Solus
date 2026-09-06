// Copy helpers for Home's connected-accounts card (SOLUSDEV-241). Pure, so the
// card file exports only components (fast refresh) and the words are testable
// without rendering.
import type { Connection, LegacyConnection } from '../../lib/api/resources'

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

function projectWords(legacy: LegacyConnection): { where: string; they: string; keep: string } {
  const names = legacy.projects.map((p) => p.name).filter(Boolean)
  if (names.length === 0) return { where: 'a project', they: 'it', keep: 'keeps' }
  if (names.length === 1) return { where: names[0], they: names[0], keep: 'keeps' }
  const where = names.length <= 2 ? names.join(' and ') : `${names.length} projects`
  return { where, they: 'those projects', keep: 'keep' }
}

/** A project-scoped grant not yet at account scope: where it is used, and
 *  what moves it. Plain about what keeps working meanwhile. */
export function legacyText(legacy: LegacyConnection): string {
  const { where, they, keep } = projectWords(legacy)
  if (legacy.claimable_connection_id) {
    return (
      `Connected in ${where} before account-level connections. Your linked account matches — ` +
      `move it so ${they} use${they === 'it' || they === where ? 's' : ''} your account grant.`
    )
  }
  return (
    `Connected in ${where} before account-level connections. Sign in once to move it to ` +
    `your account — ${they} ${keep} syncing until then.`
  )
}

/** The confirmation must say exactly what a move does (CLAUDE.md §7). */
export function moveDetail(
  providerName: string,
  legacy: LegacyConnection,
  grant: Connection
): string {
  const { where } = projectWords(legacy)
  const scope = scopeText(grant).toLowerCase()
  const own = legacy.projects.length > 1 ? "Each project's own" : "The project's own"
  return (
    `${where} will use your linked ${providerName} account (${scope} access). ` +
    `${own} ${providerName} token — and any add-on grant on it — is removed; ` +
    `syncing continues on your account.`
  )
}

/** Why the row asks for a fresh sign-in, or null. Never forces it: the
 *  existing token keeps working until the new consent succeeds. H4: a bound
 *  source the provider rejected also means the grant is gone. */
export function reauthText(connection: Connection): string | null {
  if (connection.needs_reauth === 'token_error' || connection.status === 'error') {
    const message = connection.last_error?.message?.trim()
    if (!message) return 'The last sign-in failed. Re-authorize to reconnect.'
    const sentence = /[.!?]$/.test(message) ? message : `${message}.`
    return `${sentence} Re-authorize to reconnect.`
  }
  if (connection.health === 'token_expired') {
    return "The provider rejected this account's token. Re-authorize to reconnect."
  }
  return null
}

/** The badge word for the derived health (SOLUSDEV-244 / H4). */
export function healthLabel(connection: Connection): 'Healthy' | 'Token expired' | 'Degraded' {
  if (connection.health === 'token_expired') return 'Token expired'
  if (connection.health === 'degraded') return 'Degraded'
  return 'Healthy'
}

const number = new Intl.NumberFormat('en-US')

/** The meter's position, always labelled an estimate (ADR-019): a floor on
 *  Solus's own calls, never a balance. Null when the provider is unmetered or
 *  the ledger was unreachable — nothing is said rather than something invented. */
export function quotaText(connection: Connection, providerName: string): string | null {
  const quota = connection.quota
  if (!quota) return null
  return `At least ${number.format(quota.used)} of ${number.format(quota.allowance)} ${providerName} calls this year (estimate)`
}

/** What is already degraded, or what will, stated BEFORE the wall (H4). */
export function quotaNote(connection: Connection, providerName: string): string | null {
  const quota = connection.quota
  if (!quota || quota.status === 'ok') return null
  if (quota.status === 'exhausted') {
    return (
      `${providerName}'s call limit is reached, so Solus is in cache-only mode: documents already ` +
      `synced stay readable, nothing new is fetched and no syncs run until the allowance resets. ` +
      `This is not an error and needs no sign-in.`
    )
  }
  return (
    `Approaching ${providerName}'s call limit. Automatic syncs and SOL's ${providerName} calls are ` +
    `paused; your own Sync now still reaches ${providerName}. At the limit Solus switches to ` +
    `cache-only reads and starts no new syncs.`
  )
}

/** 0..1 of the allowance used, for the meter bar; clamped. */
export function quotaFraction(connection: Connection): number {
  const quota = connection.quota
  if (!quota || quota.allowance <= 0) return 0
  return Math.min(1, quota.used / quota.allowance)
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
