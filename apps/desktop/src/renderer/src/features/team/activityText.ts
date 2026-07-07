// Humanize backend activity rows (services/activity.py types + payloads) into
// feed sentences. Pure — new event types degrade to a readable fallback.
import type { ActivityApi, TeamMemberApi } from '../../lib/api/resources'

export function actorName(actorId: string | null, members: readonly TeamMemberApi[]): string {
  if (!actorId) return 'Someone'
  const member = members.find((m) => m.user_id === actorId)
  if (!member) return 'Someone'
  return member.name ?? member.email.split('@')[0]
}

type Texter = (p: Record<string, unknown>) => string
const str = (v: unknown): string => (typeof v === 'string' ? v : '')

const TEXTERS: Record<string, Texter> = {
  'team.created': () => 'created the team',
  'team.renamed': (p) => `renamed the team to "${str(p.name)}"`,
  'team.upgraded': () => 'upgraded to a shared team',
  'team.settings_updated': () => 'updated team settings',
  'invite.created': (p) => `invited ${str(p.email)} as ${str(p.role)}`,
  'invite.accepted': (p) => `joined the team (${str(p.email)})`,
  'invite.revoked': (p) => `revoked the invite for ${str(p.email)}`,
  'member.role_changed': (p) => `changed a member role to ${str(p.role)}`,
  'member.removed': () => 'removed a member',
  'member.left': () => 'left the team',
  'project.created': (p) => `created the project "${str(p.name)}"`,
  'project.updated': () => 'updated a project',
  'project.archived': (p) => `archived the project "${str(p.name)}"`,
  'project.unarchived': (p) => `restored the project "${str(p.name)}"`,
  'project.deleted': (p) => `deleted the project "${str(p.name)}"`,
  'source.connected': (p) => `connected ${str(p.type)} source "${str(p.name)}"`,
  'source.disconnected': (p) => `disconnected a ${str(p.type)} source`,
  'source.sync_started': () => 'started a source sync',
  'job.cancelled': (p) => `cancelled a ${str(p.kind)} job`
}

export function activityText(a: ActivityApi): string {
  const texter = TEXTERS[a.type]
  if (texter) return texter(a.payload)
  return a.type.replace('.', ': ').replace(/_/g, ' ')
}
