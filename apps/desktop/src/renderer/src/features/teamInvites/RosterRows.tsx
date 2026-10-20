// SOLUSDEV-317 (design A): one <tr> per People-table row — a teammate, a
// pending invite, or an org member who is not on the team. Every value the
// server or GitHub supplies is rendered as text; avatars only over https.
import { Avatar } from '../../components/ui/Avatar'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { relativeTime } from '../../lib/relativeTime'
import type { InviteApi, TeamMemberApi, TeamRole } from '../../lib/api/resources'
import type { GithubOrgMember } from '../../lib/api/resources.teamGithub'
import type { SolMode } from '../../store/settingsStore'
import { AssignPicker } from '../workspace/AssignPicker'
import { safeHttpsUrl } from '../workspace/githubInstallFlow'
import { githubText } from '../workspace/githubOrgCopy'
import { ROLE_LABEL, type PickerOption } from '../workspace/githubOrgMembersView'
import { homeStagger } from '../workspace/homeMotion'
import type { RowState } from '../workspace/useGithubOrgRoster'
import { MemberGithubCell } from './MemberGithubCell'
import type { MemberLink } from './rosterModel'
import { RowFeedback } from './RowFeedback'

/** Assignable roles (owner is transferred, not picked). */
const ASSIGNABLE_ROLES = ['admin', 'member', 'viewer'] as const

const DAY_MS = 86_400_000

const TD: React.CSSProperties = { padding: '10px 8px', verticalAlign: 'middle' }
const TD_FIRST: React.CSSProperties = { ...TD, paddingLeft: 16 }
const TD_LAST: React.CSSProperties = {
  ...TD,
  paddingRight: 16,
  textAlign: 'right',
  whiteSpace: 'nowrap'
}

const SELECT: React.CSSProperties = {
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '4px 6px',
  fontSize: 11,
  fontFamily: 'var(--font-ui)'
}

const ICON_BUTTON: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  color: 'var(--mut)',
  cursor: 'pointer',
  padding: 4
}

function RowShell({
  index,
  children
}: {
  index: number
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <tr className="home-row-in" style={{ ...homeStagger(index), borderTop: '1px solid var(--bd)' }}>
      {children}
    </tr>
  )
}

function Person({
  label,
  sub,
  avatar
}: {
  label: string
  sub: string | null
  avatar: React.ReactNode
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
      <span aria-hidden style={{ display: 'inline-flex', flexShrink: 0 }}>
        {avatar}
      </span>
      <div style={{ minWidth: 0 }}>
        <div data-person style={{ fontWeight: 600, wordBreak: 'break-all' }}>
          {label}
        </div>
        {sub && (
          <div style={{ color: 'var(--mut)', fontSize: 11, wordBreak: 'break-all' }}>{sub}</div>
        )}
      </div>
    </div>
  )
}

export interface MemberRowProps {
  index: number
  member: TeamMemberApi
  link: MemberLink | null
  canManage: boolean
  canLink: boolean
  options: readonly PickerOption[]
  rows: Readonly<Record<number, RowState>>
  mode: SolMode
  onChangeRole: (userId: string, role: TeamRole) => void
  onRemove: (member: TeamMemberApi) => void
  onLink: (githubId: number, member: TeamMemberApi) => void
  onUnlink: (githubId: number) => void
  onFind: (login: string) => void
}

export function MemberRow(props: MemberRowProps): React.JSX.Element {
  const { member, canManage } = props
  const name = member.name ?? member.email
  const editable = canManage && member.role !== 'owner'
  return (
    <RowShell index={props.index}>
      <th scope="row" style={{ ...TD_FIRST, textAlign: 'left', fontWeight: 400 }}>
        <Person
          label={name}
          sub={member.name ? member.email : null}
          avatar={<Avatar name={name} size={28} />}
        />
      </th>
      <td style={TD}>
        {editable ? (
          <select
            aria-label={`Role for ${member.email}`}
            value={member.role}
            onChange={(e) => props.onChangeRole(member.user_id, e.target.value as TeamRole)}
            style={SELECT}
          >
            {ASSIGNABLE_ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]}
              </option>
            ))}
          </select>
        ) : (
          <span style={{ color: 'var(--mut)' }}>{ROLE_LABEL[member.role]}</span>
        )}
      </td>
      <td style={TD}>
        <MemberGithubCell
          name={name}
          link={props.link}
          canLink={props.canLink}
          options={props.options}
          rows={props.rows}
          mode={props.mode}
          onLink={(id) => props.onLink(id, member)}
          onUnlink={props.onUnlink}
          onFind={props.onFind}
        />
      </td>
      <td style={TD_LAST}>
        {editable && (
          <button
            type="button"
            aria-label={`Remove ${member.email}`}
            onClick={() => props.onRemove(member)}
            style={ICON_BUTTON}
          >
            <Icons.x size={13} />
          </button>
        )}
      </td>
    </RowShell>
  )
}

function expiresText(invite: InviteApi, now: number): string {
  const days = Math.ceil((Date.parse(invite.expires_at) - now) / DAY_MS)
  if (Number.isNaN(days)) return ''
  return days <= 0 ? ' · expired' : ` · expires in ${days}d`
}

export function InviteRow({
  index,
  invite,
  canManage,
  onRevoke
}: {
  index: number
  invite: InviteApi
  canManage: boolean
  onRevoke: (invite: InviteApi) => void
}): React.JSX.Element {
  const label = invite.email ?? `@${invite.github_login ?? 'unknown'}`
  const sub = `Invite sent ${relativeTime(invite.created_at)}${expiresText(invite, Date.now())}`
  return (
    <RowShell index={index}>
      <th scope="row" style={{ ...TD_FIRST, textAlign: 'left', fontWeight: 400 }}>
        <Person label={label} sub={sub} avatar={<DashedAvatar />} />
      </th>
      <td style={{ ...TD, color: 'var(--mut)' }}>{ROLE_LABEL[invite.role]} (pending)</td>
      <td style={TD}>
        {invite.github_login ? (
          <span style={{ display: 'inline-flex', gap: 6, alignItems: 'baseline' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5 }}>
              @{invite.github_login}
            </span>
            <Mono size={9} color="var(--warn)">
              INVITED
            </Mono>
          </span>
        ) : (
          <span style={{ color: 'var(--mut)' }}>—</span>
        )}
      </td>
      <td style={TD_LAST}>
        {canManage && (
          <Button
            kind="ghost"
            size="sm"
            aria-label={`Revoke invite for ${label}`}
            onClick={() => onRevoke(invite)}
          >
            Revoke
          </Button>
        )}
      </td>
    </RowShell>
  )
}

function DashedAvatar(): React.JSX.Element {
  return (
    <span
      aria-hidden
      style={{
        width: 28,
        height: 28,
        flexShrink: 0,
        boxSizing: 'border-box',
        borderRadius: 99,
        border: '1px dashed var(--bd)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--mut)'
      }}
    >
      <Icons.team size={13} />
    </span>
  )
}

function OrgAvatar({ url, login }: { url: string | null; login: string }): React.JSX.Element {
  const src = safeHttpsUrl(url)
  if (!src) return <Avatar name={login} size={28} />
  return (
    <img
      src={src}
      alt=""
      style={{ width: 28, height: 28, borderRadius: 99, objectFit: 'cover', flexShrink: 0 }}
    />
  )
}

export interface OrgRowProps {
  index: number
  org: GithubOrgMember
  state: RowState | undefined
  options: readonly PickerOption[]
  mode: SolMode
  onAssign: (userId: string) => void
  onInvite: () => void
  onFind: (login: string) => void
  onUpgrade?: () => void
}

export function OrgRow(props: OrgRowProps): React.JSX.Element {
  const { org, state, mode } = props
  const invited = org.solus_status === 'invited'
  return (
    <RowShell index={props.index}>
      <th scope="row" style={{ ...TD_FIRST, textAlign: 'left', fontWeight: 400 }}>
        <Person
          label={`@${org.github_login}`}
          sub={null}
          avatar={<OrgAvatar url={org.avatar_url} login={org.github_login} />}
        />
      </th>
      <td style={{ ...TD, color: 'var(--mut)' }}>—</td>
      <td style={TD}>
        <Mono size={9} color={invited ? 'var(--warn)' : 'var(--mut)'}>
          {invited ? 'INVITED' : 'NOT ON SOLUS'}
        </Mono>
        <RowFeedback state={state} mode={mode} onFind={props.onFind} onUpgrade={props.onUpgrade} />
      </td>
      <td style={TD_LAST}>
        <span style={{ display: 'inline-flex', gap: 6 }}>
          <AssignPicker
            label="Link to teammate…"
            listLabel={`Teammate for @${org.github_login}`}
            options={props.options}
            emptyText={githubText('no_teammates_left', mode)}
            onPick={props.onAssign}
          />
          {!invited && (
            <Button
              kind="ghost"
              size="sm"
              disabled={state?.pending}
              aria-label={`Invite @${org.github_login}`}
              onClick={props.onInvite}
            >
              Invite
            </Button>
          )}
        </span>
      </td>
    </RowShell>
  )
}
