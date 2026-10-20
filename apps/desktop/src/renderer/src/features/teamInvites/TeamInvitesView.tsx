// SOLUSDEV-317 (design A, "one roster"): Home's Team & invites view. A header
// (team, counts, search, Invite), the GitHub organization as a strip — or, on
// a solo team, two setup steps — then ONE People table (teammates, pending
// invites, org members not on the team) beside the team activity rail. One
// useTeamGithub feeds the strip and the table; the org roster is fetched only
// for an owner/admin with a live Organization link. Keyed by team in HomeScreen.
import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import type { TeamMemberApi, TeamSummary } from '../../lib/api/resources'
import type { GithubOrgMember } from '../../lib/api/resources.teamGithub'
import { liveKeys, useLiveRevisionStore } from '../../store/liveRevisionStore'
import { useSettingsStore, type SolMode } from '../../store/settingsStore'
import {
  MembershipConfirmation,
  memberFailureText,
  MEMBER_FAILURE,
  type PendingConfirm
} from '../team/MembersPanel'
import { GitHubOrgCard } from '../workspace/GitHubOrgCard'
import { githubText } from '../workspace/githubOrgCopy'
import { useGithubInviteTokenStore } from '../workspace/githubInviteTokenStore'
import { TeamActivityPanel } from '../workspace/TeamActivityPanel'
import { useGithubOrgRoster, type GithubOrgRoster } from '../workspace/useGithubOrgRoster'
import type { HomeTeam, MemberOutcome } from '../workspace/useHomeTeam'
import { useTeamGithub, type TeamGithub } from '../workspace/useTeamGithub'
import {
  buildRoster,
  filterRoster,
  rosterFilters,
  summaryCounts,
  type RosterFilter
} from './rosterModel'
import { RosterTable } from './RosterTable'
import { teamText } from './teamInvitesCopy'
import { showsLinkStep, TeamSetupSteps } from './TeamSetupSteps'

export interface TeamInvitesViewProps {
  team: TeamSummary
  homeTeam: HomeTeam
  canManage: boolean
  /** Opens the email invite dialog. */
  onInvite: () => void
  onUpgrade?: () => void
}

/** The org roster needs an owner/admin AND a live Organization link. */
export function showsOrgRoster(github: TeamGithub, canManage: boolean): boolean {
  const link = github.installation
  return canManage && link?.account_type === 'Organization' && link.status === 'active'
}

/** The GitHub layer: the installation, and the org roster when it applies. */
function useTeamGithubLayer(team: TeamSummary, canManage: boolean) {
  const github = useTeamGithub(team.is_personal ? null : team.team_id)
  const hasOrg = showsOrgRoster(github, canManage)
  const roster = useGithubOrgRoster({
    teamId: team.team_id,
    enabled: hasOrg,
    inviteMember: github.actions.inviteMember,
    onMembersStale: () =>
      useLiveRevisionStore.getState().bump([liveKeys.teamMembers(team.team_id)]),
    onLinkStale: () => void github.actions.refresh()
  })
  return { github, hasOrg, roster: hasOrg ? roster : null }
}

const isSolo = ({ team, homeTeam, canManage }: TeamInvitesViewProps): boolean =>
  !team.is_personal && canManage && homeTeam.members.length === 1 && homeTeam.invites.length === 0

export function TeamInvitesView(props: TeamInvitesViewProps): React.JSX.Element {
  const { team, homeTeam, canManage } = props
  const mode = useSettingsStore((s) => s.solMode)
  const { github, hasOrg, roster } = useTeamGithubLayer(team, canManage)
  const headingRef = useRef<HTMLHeadingElement>(null)
  const link = useFocusAfterLink(github, hasOrg, headingRef)
  const card: TeamGithub = { ...github, actions: { ...github.actions, link } }
  const solo = isSolo(props)
  const stepShown = solo && showsLinkStep(github)
  // A solo team waits for the GitHub state, so the strip never swaps into step 2.
  const settling = solo && github.status === 'loading'
  const showStrip = !team.is_personal && github.status !== 'idle' && !stepShown && !settling
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <People
        {...props}
        mode={mode}
        solo={solo}
        roster={roster}
        orgLogin={github.installation?.account_login ?? null}
        headingRef={headingRef}
        top={
          solo && (
            <TeamSetupSteps
              teamName={team.name}
              github={card}
              mode={mode}
              onInvite={homeTeam.actions.invite}
              onUpgrade={props.onUpgrade}
            />
          )
        }
        strip={
          showStrip && (
            <GitHubOrgCard
              github={card}
              teamName={team.name}
              canManage={canManage}
              onUpgrade={props.onUpgrade}
            />
          )
        }
      />
    </div>
  )
}

/** After a link THIS admin started lands, focus moves to the People heading. */
function useFocusAfterLink(
  github: TeamGithub,
  hasOrg: boolean,
  headingRef: React.RefObject<HTMLHeadingElement | null>
): () => Promise<void> {
  const awaiting = useRef(false)
  useEffect(() => {
    if (!awaiting.current) return
    if (hasOrg) headingRef.current?.focus()
    if (hasOrg || github.notice) awaiting.current = false
  }, [hasOrg, github.notice, headingRef])
  return async () => {
    awaiting.current = true
    await github.actions.link()
  }
}

type PeopleProps = TeamInvitesViewProps & {
  mode: SolMode
  solo: boolean
  roster: GithubOrgRoster | null
  orgLogin: string | null
  headingRef: React.RefObject<HTMLHeadingElement | null>
  top: React.ReactNode
  strip: React.ReactNode
}

function People(props: PeopleProps): React.JSX.Element {
  const { homeTeam, roster, mode, canManage } = props
  const [filter, setFilter] = useState<RosterFilter>('Everyone')
  const [query, setQuery] = useState('')
  const [confirm, setConfirm] = useState<PendingConfirm>(null)
  const [error, setError] = useState<string | null>(null)
  const showToken = useGithubInviteTokenStore((s) => s.show)
  const org = roster?.status === 'ready' ? roster.items : null
  const all = buildRoster(homeTeam.members, homeTeam.invites, org)
  const partial = org !== null && Boolean(roster?.cursor)
  const refocus = useRefocusAfterConfirm(confirm, props.headingRef)
  const filters = rosterFilters(org !== null)
  const active = filters.includes(filter) ? filter : 'Everyone'
  const report = (outcome: MemberOutcome): void => setError(memberFailureText(outcome))
  const inviteOrg = async (member: GithubOrgMember): Promise<void> => {
    const outcome = await roster?.actions.invite(member)
    if (outcome?.ok)
      showToken({ invitee: `@${member.github_login}`, token: outcome.token, kind: 'github' })
  }
  return (
    <>
      <Header
        {...props}
        counts={summaryCounts(all)}
        partial={partial}
        query={query}
        onQuery={setQuery}
      />
      {props.top}
      {props.strip}
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div
          style={{
            flex: '999 1 560px',
            minWidth: 0,
            display: 'flex',
            flexDirection: 'column',
            gap: 8
          }}
        >
          <RosterTable
            rows={filterRoster(all, active, query, org)}
            total={all.length}
            partial={partial}
            filters={filters}
            filter={active}
            onFilter={setFilter}
            members={homeTeam.members}
            roster={roster}
            orgLogin={props.orgLogin}
            canManage={canManage}
            mode={mode}
            footnote={footnote(homeTeam, roster !== null, mode)}
            headingRef={props.headingRef}
            onChangeRole={(userId, role) =>
              void homeTeam.actions.changeRole(userId, role).then(report)
            }
            onRemove={(member: TeamMemberApi) => setConfirm({ kind: 'remove', member })}
            onRevoke={(invite) => setConfirm({ kind: 'revoke', invite })}
            onInviteOrg={(m) => void inviteOrg(m)}
            onFind={(login) => {
              setFilter('Everyone')
              setQuery(login)
            }}
            onUpgrade={props.onUpgrade}
          />
          <ErrorLine text={error} />
        </div>
        <ActivityRail homeTeam={homeTeam} />
      </div>
      <Confirmations
        homeTeam={homeTeam}
        confirm={confirm}
        onClose={() => setConfirm(null)}
        onDone={() => (refocus.current = true)}
      />
    </>
  )
}

function ErrorLine({ text }: { text: string | null }): React.JSX.Element | null {
  if (!text) return null
  return (
    <div role="alert" style={{ fontSize: 11.5, color: 'var(--err)' }}>
      {text}
    </div>
  )
}

function ActivityRail({ homeTeam }: { homeTeam: HomeTeam }): React.JSX.Element {
  return (
    <aside aria-label="Team activity" style={{ flex: '1 1 280px', maxWidth: 360, minWidth: 0 }}>
      <TeamActivityPanel
        activity={homeTeam.activity}
        members={homeTeam.members}
        total={homeTeam.activityTotal}
        hasMore={homeTeam.activityHasMore}
        onLoadMore={homeTeam.actions.loadMoreActivity}
      />
    </aside>
  )
}

/** Remove a member / revoke an invite: confirmed with the person named. */
function Confirmations({
  homeTeam,
  confirm,
  onClose,
  onDone
}: {
  homeTeam: HomeTeam
  confirm: PendingConfirm
  onClose: () => void
  /** The row is gone: focus must land somewhere real. */
  onDone: () => void
}): React.JSX.Element {
  return (
    <MembershipConfirmation
      confirm={confirm}
      onClose={onClose}
      confirmed={async () => {
        if (!confirm) return false
        const outcome =
          confirm.kind === 'remove'
            ? await homeTeam.actions.remove(confirm.member.user_id)
            : await homeTeam.actions.revoke(confirm.invite.id)
        if (!outcome.ok) return { message: MEMBER_FAILURE[outcome.reason] }
        onDone()
        return true
      }}
    />
  )
}

/** After a confirmed remove / revoke the focused row is gone: land on the heading. */
function useRefocusAfterConfirm(
  confirm: PendingConfirm,
  headingRef: React.RefObject<HTMLHeadingElement | null>
): React.RefObject<boolean> {
  const refocus = useRef(false)
  useEffect(() => {
    if (confirm !== null || !refocus.current) return
    refocus.current = false
    headingRef.current?.focus()
  }, [confirm, headingRef])
  return refocus
}

function footnote(homeTeam: HomeTeam, hasOrg: boolean, mode: SolMode): string {
  if (homeTeam.myRole === 'viewer') return teamText('viewer_note', mode)
  return hasOrg ? githubText('assign_intro', mode) : teamText('people_note', mode)
}

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? '' : 's'}`

function summary(
  counts: ReturnType<typeof summaryCounts>,
  orgLogin: string | null,
  partial: boolean
): string {
  const parts = [plural(counts.members, 'member')]
  if (counts.invites > 0) parts.push(plural(counts.invites, 'pending invite'))
  if (counts.outside > 0 && orgLogin) {
    // Paged: only the loaded org members are counted, so say "N+".
    const n = partial ? `${counts.outside}+` : String(counts.outside)
    const who = counts.outside === 1 && !partial ? 'person' : 'people'
    parts.push(`${n} more ${who} in ${orgLogin}`)
  }
  return parts.join(' · ')
}

function Header(
  props: PeopleProps & {
    counts: ReturnType<typeof summaryCounts>
    partial: boolean
    query: string
    onQuery: (q: string) => void
  }
): React.JSX.Element {
  const { solo } = props
  return (
    <header style={{ display: 'flex', alignItems: 'flex-end', gap: 14, flexWrap: 'wrap' }}>
      <div
        style={{ flex: '1 1 260px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4 }}
      >
        <Mono size={9.5} color="var(--mut)">
          TEAM &amp; INVITES
        </Mono>
        <h2
          style={{
            margin: 0,
            fontSize: 22,
            fontWeight: 600,
            letterSpacing: '-0.015em',
            wordBreak: 'break-all'
          }}
        >
          {props.team.name}
        </h2>
        <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>
          {solo
            ? teamText('setup_intro', props.mode)
            : summary(props.counts, props.orgLogin, props.partial)}
        </div>
      </div>
      {!solo && (
        <input
          type="search"
          aria-label="Search people"
          placeholder="Name, email or @login"
          value={props.query}
          onChange={(e) => props.onQuery(e.target.value)}
          style={{
            flex: '0 1 240px',
            minWidth: 0,
            background: 'var(--sur)',
            color: 'var(--tx)',
            border: '1px solid var(--bd)',
            borderRadius: 3,
            padding: '7px 10px',
            fontFamily: 'var(--font-ui)',
            fontSize: 12
          }}
        />
      )}
      {props.canManage && !solo && (
        <Button kind="primary" size="sm" onClick={props.onInvite}>
          <Icons.plus size={12} /> Invite teammate
        </Button>
      )}
    </header>
  )
}
