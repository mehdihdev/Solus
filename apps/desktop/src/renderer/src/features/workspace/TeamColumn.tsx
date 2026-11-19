// SOLUSDEV-328 (A2, docs/wireflows/home.md "Fills the window"): the team overview's full-height
// right column. Every member (role and when they joined) in a section capped at 40% of the column,
// managers' pending invites, then the team activity feed taking the rest of the height and paging
// older rows on request (activity-feed.md cursor paging). The personal workspace keeps only its feed.
import { useState } from 'react'
import { Avatar } from '../../components/ui/Avatar'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import type { InviteApi, TeamMemberApi, TeamSummary } from '../../lib/api/resources'
import { relativeTime } from '../../lib/relativeTime'
import { MANAGER_ROLES } from '../team/MembersPanel'
import { ActivityRow } from './TeamActivityPanel'
import { roleLabel } from './teamLabels'
import type { HomeTeam } from './useHomeTeam'

export interface TeamColumnProps {
  team: TeamSummary
  homeTeam: HomeTeam
  onManageMembers: () => void
  /** Under the projects in one page scroll, rather than a full-height column of its own. */
  stacked?: boolean
}

export function canManageTeam(homeTeam: HomeTeam): boolean {
  return homeTeam.myRole !== null && MANAGER_ROLES.includes(homeTeam.myRole)
}

/** Beside the other columns the team column is exactly the pane's height and its sections
 *  scroll on their own (members ≤ 40%, invites ≤ 25%, the feed takes the rest); stacked under
 *  the projects, every section takes its natural height inside the one page scroll. */
const FITTED: Record<'root' | 'members' | 'invites' | 'feed', React.CSSProperties> = {
  root: { display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 },
  members: { flex: '0 1 auto', maxHeight: '40%', overflowY: 'auto' },
  invites: { flex: '0 1 auto', maxHeight: '25%', overflowY: 'auto' },
  feed: { flex: '1 1 0%', minHeight: 0, overflowY: 'auto' }
}
const STACKED: typeof FITTED = {
  root: { display: 'flex', flexDirection: 'column' },
  members: {},
  invites: {},
  feed: {}
}

export function TeamColumn({
  team,
  homeTeam,
  onManageMembers,
  stacked = false
}: TeamColumnProps): React.JSX.Element {
  const fit = stacked ? STACKED : FITTED
  return (
    <div data-testid="team-column" data-fit={stacked ? 'stacked' : 'fitted'} style={fit.root}>
      {!team.is_personal && (
        <Members homeTeam={homeTeam} onManageMembers={onManageMembers} style={fit.members} />
      )}
      {!team.is_personal && (
        <PendingInvites homeTeam={homeTeam} onManageMembers={onManageMembers} style={fit.invites} />
      )}
      <ActivityFeed homeTeam={homeTeam} style={fit.feed} />
    </div>
  )
}

function Members({
  homeTeam,
  onManageMembers,
  style
}: {
  homeTeam: HomeTeam
  onManageMembers: () => void
  style: React.CSSProperties
}): React.JSX.Element {
  const { members } = homeTeam
  const ready = homeTeam.status === 'ready'
  return (
    <section aria-label="Team members" style={{ ...SECTION, ...style }}>
      <Mono size={9.5} style={{ letterSpacing: '0.08em' }}>
        MEMBERS{ready ? ` · ${members.length}` : ''}
      </Mono>
      {ready ? (
        <ul aria-label="Members" style={LIST}>
          {members.map((m) => (
            <MemberRow key={m.user_id} member={m} />
          ))}
        </ul>
      ) : (
        <span style={NOTE}>Loading the team…</span>
      )}
      {ready && (
        <button type="button" className="interactive" onClick={onManageMembers} style={LINK}>
          All {members.length} {members.length === 1 ? 'member' : 'members'} and invites
        </button>
      )}
    </section>
  )
}

function MemberRow({ member }: { member: TeamMemberApi }): React.JSX.Element {
  const name = member.name ?? member.email
  return (
    <li title={member.email} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <Avatar name={name} size={24} />
      <span style={{ display: 'grid', gap: 1, minWidth: 0 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>{name}</span>
        <span style={{ fontSize: 11, color: 'var(--mut)' }}>
          {roleLabel(member.role)} · joined {relativeTime(member.joined_at)}
        </span>
      </span>
    </li>
  )
}

function inviteeLabel(invite: InviteApi): string {
  return invite.email ?? (invite.github_login ? `@${invite.github_login}` : 'Invitee')
}

function PendingInvites({
  homeTeam,
  onManageMembers,
  style
}: {
  homeTeam: HomeTeam
  onManageMembers: () => void
  style: React.CSSProperties
}): React.JSX.Element | null {
  if (!canManageTeam(homeTeam) || homeTeam.invites.length === 0) return null
  return (
    <section
      aria-label="Pending invites"
      style={{ ...SECTION, ...style, borderTop: '1px dashed var(--bd)' }}
    >
      <Mono size={9.5} style={{ letterSpacing: '0.08em' }}>
        PENDING INVITES · {homeTeam.invites.length}
      </Mono>
      {homeTeam.invites.slice(0, 4).map((invite) => (
        <span key={invite.id} style={NOTE}>
          {inviteeLabel(invite)} · {roleLabel(invite.role)} · sent {relativeTime(invite.created_at)}
        </span>
      ))}
      <button type="button" className="interactive" onClick={onManageMembers} style={LINK}>
        Manage invites
      </button>
    </section>
  )
}

function ActivityFeed({
  homeTeam,
  style
}: {
  homeTeam: HomeTeam
  style: React.CSSProperties
}): React.JSX.Element {
  const [loading, setLoading] = useState(false)
  const loadOlder = async (): Promise<void> => {
    if (loading) return
    setLoading(true)
    try {
      await homeTeam.actions.loadMoreActivity()
    } finally {
      setLoading(false)
    }
  }
  return (
    <section
      aria-label="Team activity"
      style={{
        ...SECTION,
        ...style,
        overflowX: 'hidden',
        borderTop: '1px solid var(--bd)',
        gap: 0
      }}
    >
      <Mono size={9.5} style={{ letterSpacing: '0.08em', marginBottom: 4 }}>
        TEAM ACTIVITY
      </Mono>
      {homeTeam.activity.length === 0 && (
        <span style={{ ...NOTE, padding: '8px 0' }}>
          No activity yet. Syncs, invites, and project changes will show up here.
        </span>
      )}
      <div style={{ margin: '0 -16px' }}>
        {homeTeam.activity.map((row) => (
          <ActivityRow key={row.id} row={row} members={homeTeam.members} />
        ))}
      </div>
      {homeTeam.activityHasMore && (
        <div style={{ paddingTop: 12 }}>
          <Button kind="ghost" size="sm" disabled={loading} onClick={() => void loadOlder()}>
            {loading ? 'Loading…' : 'Load older activity'}
          </Button>
        </div>
      )}
    </section>
  )
}

const SECTION: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
  padding: 16,
  flex: 'none',
  minHeight: 0
}

const LIST: React.CSSProperties = {
  listStyle: 'none',
  margin: 0,
  padding: 0,
  display: 'grid',
  gap: 10
}

const NOTE: React.CSSProperties = { fontSize: 12, color: 'var(--mut)', lineHeight: 1.5 }

const LINK: React.CSSProperties = {
  alignSelf: 'flex-start',
  background: 'transparent',
  border: 'none',
  padding: 0,
  color: 'var(--acc)',
  cursor: 'pointer',
  fontFamily: 'var(--font-ui)',
  fontSize: 12,
  textAlign: 'left'
}
