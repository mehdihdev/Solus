// SOLUSDEV-317 (design A, "one roster"): the People table — teammates, pending
// invites, then org members not on the team — under one filter and one search.
// The org part exists only for admins with a live Organization link.
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Segmented } from '../../components/ui/Segmented'
import { Spinner } from '../../components/ui/Spinner'
import type { InviteApi, TeamMemberApi, TeamRole } from '../../lib/api/resources'
import type { SolMode } from '../../store/settingsStore'
import { githubText } from '../workspace/githubOrgCopy'
import { orgMemberOptions, teammateOptions } from '../workspace/githubOrgMembersView'
import type { GithubOrgMember } from '../../lib/api/resources.teamGithub'
import type { GithubOrgRoster } from '../workspace/useGithubOrgRoster'
import { memberLink, type RosterFilter, type RosterRow } from './rosterModel'
import { InviteRow, MemberRow, OrgRow } from './RosterRows'

export interface RosterTableProps {
  rows: readonly RosterRow[]
  total: number
  /** More org members are on pages not loaded yet: counts read "N+". */
  partial: boolean
  filters: readonly RosterFilter[]
  filter: RosterFilter
  onFilter: (filter: RosterFilter) => void
  members: readonly TeamMemberApi[]
  /** Null without a live Organization link or for non-admins. */
  roster: GithubOrgRoster | null
  orgLogin: string | null
  canManage: boolean
  mode: SolMode
  footnote: string
  headingRef: React.RefObject<HTMLHeadingElement | null>
  onChangeRole: (userId: string, role: TeamRole) => void
  onRemove: (member: TeamMemberApi) => void
  onRevoke: (invite: InviteApi) => void
  onInviteOrg: (member: GithubOrgMember) => void
  onFind: (login: string) => void
  onUpgrade?: () => void
}

const TH: React.CSSProperties = {
  padding: '8px',
  fontWeight: 500,
  fontFamily: 'var(--font-mono)',
  fontSize: 9.5,
  letterSpacing: '0.08em',
  color: 'var(--mut)',
  textAlign: 'left'
}

const CELL_NOTE: React.CSSProperties = { padding: '12px 16px', fontSize: 12, color: 'var(--mut)' }

export function RosterTable(props: RosterTableProps): React.JSX.Element {
  const { mode } = props
  return (
    <section
      aria-labelledby="people-heading"
      style={{
        minWidth: 0,
        border: '1px solid var(--bd)',
        borderRadius: 4,
        background: 'var(--sur)'
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '10px 16px',
          borderBottom: '1px solid var(--bd)',
          flexWrap: 'wrap'
        }}
      >
        <h3
          id="people-heading"
          ref={props.headingRef}
          tabIndex={-1}
          aria-label={`People, ${props.total}${props.partial ? '+' : ''}`}
          style={{ margin: 0, outline: 'none', lineHeight: 1, flex: '1 1 auto' }}
        >
          <Mono size={10} color="var(--mut)">
            PEOPLE · {props.total}
            {props.partial ? '+' : ''}
          </Mono>
        </h3>
        <Segmented
          options={props.filters}
          value={props.filter}
          onChange={props.onFilter}
          size="sm"
          ariaLabel="Show"
        />
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', minWidth: 720, borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr>
              <th scope="col" style={{ ...TH, paddingLeft: 16 }}>
                PERSON
              </th>
              <th scope="col" style={TH}>
                ROLE
              </th>
              <th scope="col" style={TH}>
                GITHUB
              </th>
              <th scope="col" style={{ ...TH, paddingRight: 16, textAlign: 'right' }}>
                ACTIONS
              </th>
            </tr>
          </thead>
          <tbody>
            <Rows {...props} />
            <OrgState {...props} />
          </tbody>
        </table>
      </div>
      {props.rows.length === 0 && <div style={CELL_NOTE}>{githubText('filter_empty', mode)}</div>}
      <Footer {...props} />
    </section>
  )
}

function Rows(props: RosterTableProps): React.JSX.Element {
  const { roster, members, mode, canManage } = props
  const items = roster?.items ?? null
  // Link controls only once the org roster is loaded (not while loading or failed).
  const canLink = canManage && roster?.status === 'ready'
  const linkOptions = items ? orgMemberOptions(items) : []
  const firstOrg = props.rows.findIndex((r) => r.kind === 'org')
  const orgCount = props.rows.filter((r) => r.kind === 'org').length
  return (
    <>
      {props.rows.map((row, i) => (
        <Row
          key={`${row.kind}:${row.key}`}
          row={row}
          index={i}
          groupHeader={
            i === firstOrg
              ? `IN ${(props.orgLogin ?? '').toUpperCase()}, NOT ON THIS TEAM · ${orgCount}`
              : null
          }
          {...props}
          canLink={canLink}
          linkOptions={linkOptions}
          items={items}
          members={members}
          mode={mode}
        />
      ))}
    </>
  )
}

type RowProps = RosterTableProps & {
  row: RosterRow
  index: number
  groupHeader: string | null
  canLink: boolean
  linkOptions: ReturnType<typeof orgMemberOptions>
  items: GithubOrgMember[] | null
}

function Row(props: RowProps): React.JSX.Element {
  const { row, index, roster, items, mode } = props
  if (row.kind === 'invite') {
    return (
      <InviteRow
        index={index}
        invite={row.invite}
        canManage={props.canManage}
        onRevoke={props.onRevoke}
      />
    )
  }
  if (row.kind === 'member') {
    return (
      <MemberRow
        index={index}
        member={row.member}
        link={memberLink(row.member, items)}
        canManage={props.canManage}
        canLink={props.canLink}
        options={props.linkOptions}
        rows={roster?.rows ?? {}}
        mode={mode}
        onChangeRole={props.onChangeRole}
        onRemove={props.onRemove}
        onLink={(githubId, member) => void roster?.actions.assign(githubId, member)}
        onUnlink={(githubId) => void roster?.actions.unassign(githubId)}
        onFind={props.onFind}
      />
    )
  }
  return (
    <>
      {props.groupHeader && <GroupRow text={props.groupHeader} />}
      <OrgRow
        index={index}
        org={row.org}
        state={roster?.rows[row.org.github_id]}
        options={teammateOptions(props.members, items ?? [], row.org)}
        mode={mode}
        onAssign={(userId) => {
          const teammate = props.members.find((m) => m.user_id === userId)
          if (teammate) void roster?.actions.assign(row.org.github_id, teammate)
        }}
        onInvite={() => props.onInviteOrg(row.org)}
        onFind={props.onFind}
        onUpgrade={props.onUpgrade}
      />
    </>
  )
}

function GroupRow({ text }: { text: string }): React.JSX.Element {
  return (
    <tr style={{ borderTop: '1px solid var(--bd)', background: 'var(--sur2)' }}>
      <th colSpan={4} scope="rowgroup" style={{ ...TH, paddingLeft: 16 }}>
        {text}
      </th>
    </tr>
  )
}

/** The org part's own loading / failure, inside the table. */
function OrgState({ roster, mode }: RosterTableProps): React.JSX.Element | null {
  if (!roster || roster.status === 'ready' || roster.status === 'idle') return null
  return (
    <tr style={{ borderTop: '1px solid var(--bd)' }}>
      <td colSpan={4} style={CELL_NOTE}>
        {roster.status === 'loading' ? (
          <Spinner size={13} />
        ) : (
          <span style={{ display: 'inline-flex', gap: 10, alignItems: 'center' }}>
            <span role="status">{githubText('roster_failed', mode)}</span>
            <Button kind="ghost" size="sm" onClick={() => void roster.actions.retry()}>
              Retry
            </Button>
          </span>
        )}
      </td>
    </tr>
  )
}

function Footer({ roster, footnote }: RosterTableProps): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        flexWrap: 'wrap',
        padding: '10px 16px',
        borderTop: '1px solid var(--bd)'
      }}
    >
      <span style={{ flex: '1 1 320px', fontSize: 11.5, color: 'var(--mut)', lineHeight: 1.5 }}>
        {footnote}
      </span>
      {roster?.cursor &&
        (roster.loadingMore ? (
          <Spinner size={13} />
        ) : (
          <Button kind="ghost" size="sm" onClick={() => void roster.actions.loadMore()}>
            Load more
          </Button>
        ))}
    </div>
  )
}
