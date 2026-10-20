// SOLUSDEV-317 (ADR-039 amendment 2026-10-19): GITHUB ORG MEMBERS, inline in
// Home's Team & invites view under the GITHUB ORGANIZATION card. Admins see
// every org member, assign each to a teammate (a display label — never access),
// change or unassign it, and invite those not on Solus. HomeScreen mounts it
// only for an owner/admin of a collaborative team with a live Organization
// link, keyed by team, so nobody else ever makes the (403) roster call.
import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Segmented } from '../../components/ui/Segmented'
import { Spinner } from '../../components/ui/Spinner'
import type { TeamMemberApi } from '../../lib/api/resources'
import type { GithubOrgMember } from '../../lib/api/resources.teamGithub'
import { useSettingsStore, type SolMode } from '../../store/settingsStore'
import { useGithubAssignFocusStore } from './githubAssignFocusStore'
import { githubText } from './githubOrgCopy'
import {
  filterOrgMembers,
  onTeamCount,
  orgMemberOptions,
  teammateOptions,
  unassignedTeammates,
  ORG_FILTERS,
  type OrgFilter
} from './githubOrgMembersView'
import { useGithubInviteTokenStore } from './githubInviteTokenStore'
import { GitHubOrgMemberRow } from './GitHubOrgMemberRow'
import { UnassignedTeammateRow } from './UnassignedTeammateRow'
import { useGithubOrgRoster, type GithubOrgRoster } from './useGithubOrgRoster'
import type { MemberInviteOutcome } from './useTeamGithub'

export interface GitHubOrgMembersSectionProps {
  teamId: string
  members: readonly TeamMemberApi[]
  inviteMember: (member: GithubOrgMember) => Promise<MemberInviteOutcome>
  onMembersStale: () => void
  onLinkStale: () => void
  onUpgrade?: () => void
  /** Focus the heading on mount (right after this admin linked the org). */
  autoFocus?: boolean
}

const BOX: React.CSSProperties = {
  background: 'var(--sur)',
  border: '1px solid var(--bd)',
  borderRadius: 4
}

const SEARCH: React.CSSProperties = {
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '5px 9px',
  fontSize: 12,
  fontFamily: 'var(--font-ui)',
  outline: 'none',
  minWidth: 0,
  flex: '1 1 160px',
  maxWidth: 260
}

const NOTE: React.CSSProperties = { padding: '14px', fontSize: 12, color: 'var(--mut)' }

export function GitHubOrgMembersSection(props: GitHubOrgMembersSectionProps): React.JSX.Element {
  const mode = useSettingsStore((s) => s.solMode)
  const roster = useGithubOrgRoster({ ...props, enabled: true })
  const [filter, setFilter] = useState<OrgFilter>('All')
  const [query, setQuery] = useState('')
  const showToken = useGithubInviteTokenStore((s) => s.show)
  const headingRef = useRef<HTMLHeadingElement>(null)
  const headingId = useId()
  const [openFor, clearOpenFor] = useAssignRequest(props.teamId, headingRef, () => {
    setFilter('Unassigned teammates')
    setQuery('')
  })
  useEffect(() => {
    if (props.autoFocus) headingRef.current?.focus()
  }, [props.autoFocus])

  const invite = async (member: GithubOrgMember): Promise<void> => {
    const outcome = await roster.actions.invite(member)
    if (outcome.ok) showToken({ login: member.github_login, token: outcome.token })
  }
  return (
    <section aria-labelledby={headingId} data-testid="github-org-members" style={{ minWidth: 0 }}>
      <h2
        id={headingId}
        ref={headingRef}
        tabIndex={-1}
        aria-label="GitHub org members"
        style={{ margin: '0 0 10px', outline: 'none', lineHeight: 1 }}
      >
        <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
          GITHUB ORG MEMBERS
        </Mono>
      </h2>
      <div style={BOX}>
        <Intro mode={mode} />
        <Toolbar
          roster={roster}
          mode={mode}
          filter={filter}
          query={query}
          onFilter={(next) => {
            // A members-list request opens its picker once, not on every revisit.
            clearOpenFor()
            setFilter(next)
          }}
          onQuery={setQuery}
        />
        <Body
          {...props}
          roster={roster}
          mode={mode}
          filter={filter}
          query={query}
          openFor={openFor}
          onInvite={(m) => void invite(m)}
          onFind={(login) => {
            setFilter('All')
            setQuery(login)
          }}
        />
      </div>
    </section>
  )
}

/** Answers "Assign GitHub…" from the members list: scroll here, then open that
 *  teammate's picker. Returns the teammate and request number to open for. */
function useAssignRequest(
  teamId: string,
  headingRef: React.RefObject<HTMLHeadingElement | null>,
  onRequest: () => void
): [{ userId: string; seq: number } | null, () => void] {
  const request = useGithubAssignFocusStore((s) => s.request)
  const clear = useGithubAssignFocusStore((s) => s.clear)
  const [openFor, setOpenFor] = useState<{ userId: string; seq: number } | null>(null)
  const latest = useRef(onRequest)
  latest.current = onRequest
  useEffect(() => {
    if (!request || request.teamId !== teamId) return
    latest.current()
    setOpenFor({ userId: request.userId, seq: request.seq })
    headingRef.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
    clear()
  }, [request, teamId, headingRef, clear])
  return [openFor, () => setOpenFor(null)]
}

function Intro({ mode }: { mode: SolMode }): React.JSX.Element {
  return (
    <div
      style={{
        padding: '12px 14px',
        fontSize: mode === 'Guide' ? 12.5 : 11.5,
        color: 'var(--mut)',
        lineHeight: 1.55,
        borderBottom: '1px solid var(--bd)'
      }}
    >
      {githubText('assign_intro', mode)}
    </div>
  )
}

interface ToolbarProps {
  roster: GithubOrgRoster
  mode: SolMode
  filter: OrgFilter
  query: string
  onFilter: (filter: OrgFilter) => void
  onQuery: (query: string) => void
}

function Toolbar({
  roster,
  mode,
  filter,
  query,
  onFilter,
  onQuery
}: ToolbarProps): React.JSX.Element {
  const n = roster.total ?? roster.items.length
  return (
    <div
      style={{
        display: 'flex',
        gap: 10,
        alignItems: 'center',
        flexWrap: 'wrap',
        padding: '10px 14px',
        borderBottom: '1px solid var(--bd)'
      }}
    >
      <span style={{ fontSize: 12, fontWeight: 600, flex: '1 1 auto' }}>
        {githubText('roster_count', mode, { n, m: onTeamCount(roster.items) })}
      </span>
      <input
        type="search"
        aria-label={filter === 'Unassigned teammates' ? 'Search teammates' : 'Search org members'}
        placeholder="Search…"
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        style={SEARCH}
      />
      <Segmented
        options={ORG_FILTERS}
        value={filter}
        onChange={onFilter}
        size="sm"
        ariaLabel="Show"
      />
    </div>
  )
}

type BodyProps = GitHubOrgMembersSectionProps & {
  roster: GithubOrgRoster
  mode: SolMode
  filter: OrgFilter
  query: string
  openFor: { userId: string; seq: number } | null
  onInvite: (member: GithubOrgMember) => void
  onFind: (login: string) => void
}

function Body(props: BodyProps): React.JSX.Element {
  const { roster, mode } = props
  if (roster.status === 'loading' || roster.status === 'idle') {
    return (
      <div style={NOTE}>
        <Spinner size={14} />
      </div>
    )
  }
  if (roster.status === 'failed') {
    return (
      <div style={{ ...NOTE, display: 'flex', gap: 10, alignItems: 'center' }}>
        <span role="status">{githubText('roster_failed', mode)}</span>
        <Button kind="ghost" size="sm" onClick={() => void roster.actions.retry()}>
          Retry
        </Button>
      </div>
    )
  }
  if (roster.items.length === 0) return <div style={NOTE}>{githubText('roster_empty', mode)}</div>
  return props.filter === 'Unassigned teammates' ? (
    <TeammateList {...props} />
  ) : (
    <OrgList {...props} />
  )
}

function OrgList({
  roster,
  members,
  mode,
  filter,
  query,
  onInvite,
  onFind,
  onUpgrade
}: BodyProps): React.JSX.Element {
  const shown = filterOrgMembers(roster.items, filter, query)
  return (
    <>
      <ul aria-label="GitHub org members" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {shown.map((m, i) => (
          <GitHubOrgMemberRow
            key={m.github_id}
            member={m}
            index={i}
            state={roster.rows[m.github_id]}
            options={teammateOptions(members, roster.items, m)}
            mode={mode}
            onAssign={(userId) => {
              const teammate = members.find((t) => t.user_id === userId)
              if (teammate) void roster.actions.assign(m.github_id, teammate)
            }}
            onUnassign={() => void roster.actions.unassign(m.github_id)}
            onInvite={() => onInvite(m)}
            onFind={onFind}
            onUpgrade={onUpgrade}
          />
        ))}
      </ul>
      {shown.length === 0 && <div style={NOTE}>{githubText('filter_empty', mode)}</div>}
      <LoadMore roster={roster} />
    </>
  )
}

function TeammateList({ roster, members, mode, query, openFor }: BodyProps): React.JSX.Element {
  const teammates = unassignedTeammates(members, roster.items, query)
  const options = orgMemberOptions(roster.items)
  if (teammates.length === 0)
    return <div style={NOTE}>{githubText('teammates_all_linked', mode)}</div>
  return (
    <>
      <ul aria-label="Unassigned teammates" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {teammates.map((t, i) => (
          <UnassignedTeammateRow
            key={t.user_id}
            teammate={t}
            index={i}
            options={options}
            rows={roster.rows}
            mode={mode}
            openRequest={openFor?.userId === t.user_id ? openFor.seq : 0}
            onAssign={(githubId) => void roster.actions.assign(githubId, t)}
          />
        ))}
      </ul>
      <LoadMore roster={roster} />
    </>
  )
}

function LoadMore({ roster }: { roster: GithubOrgRoster }): React.JSX.Element | null {
  if (!roster.cursor) return null
  return (
    <div style={{ padding: '10px 14px' }}>
      {roster.loadingMore ? (
        <Spinner size={13} />
      ) : (
        <Button kind="ghost" size="sm" onClick={() => void roster.actions.loadMore()}>
          Load more
        </Button>
      )}
    </div>
  )
}
