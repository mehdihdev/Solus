// The GitHub org roster (SOLUSDEV-216 / ADR-039 §6): admin-only, Organization
// installs only. Each row: avatar, login, and a status chip (On team / Invited)
// or an Invite button for a login not on Solus. One invite at a time — no bulk
// add, no auto-join. A successful invite shows the one-time join token ONCE
// (mirroring the email InviteModal's reveal). Logins are text, never HTML.
import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'
import type { GithubOrgMember } from '../../lib/api/resources.teamGithub'
import { useSettingsStore, type SolMode } from '../../store/settingsStore'
import { safeHttpsUrl } from './githubInstallFlow'
import { githubText } from './githubOrgCopy'
import { ModalShell } from './modals'
import { PlanLimitNotice } from './PlanLimitNotice'
import type { TeamGithubActions } from './useTeamGithub'

export interface GitHubRosterModalProps {
  actions: Pick<TeamGithubActions, 'loadRoster' | 'inviteMember'>
  /** The organization's login, for the title. */
  login: string
  onClose: () => void
  onUpgrade?: () => void
}

type Problem = { kind: 'text'; text: string } | { kind: 'limit'; message: string }

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

function Row({
  member,
  busy,
  onInvite
}: {
  member: GithubOrgMember
  busy: boolean
  onInvite: (member: GithubOrgMember) => void
}): React.JSX.Element {
  const avatar = safeHttpsUrl(member.avatar_url)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0' }}>
      <span
        aria-hidden
        style={{
          width: 24,
          height: 24,
          borderRadius: 12,
          overflow: 'hidden',
          background: 'var(--sur2)',
          flexShrink: 0
        }}
      >
        {avatar && <img src={avatar} alt="" style={{ width: '100%', height: '100%' }} />}
      </span>
      <span style={{ flex: 1, minWidth: 0, fontSize: 12.5, wordBreak: 'break-all' }}>
        {member.github_login}
      </span>
      {member.solus_status === 'member' && <Chip text="On team" />}
      {member.solus_status === 'invited' && <Chip text="Invited" />}
      {member.solus_status === 'not_on_solus' && (
        <Button
          kind="soft"
          size="sm"
          disabled={busy}
          aria-label={`Invite ${member.github_login}`}
          onClick={() => onInvite(member)}
        >
          Invite
        </Button>
      )}
    </div>
  )
}

function Chip({ text }: { text: string }): React.JSX.Element {
  return (
    <span
      style={{
        fontSize: 10.5,
        fontFamily: 'var(--font-mono)',
        color: 'var(--mut)',
        border: '1px solid var(--bd)',
        borderRadius: 3,
        padding: '2px 7px'
      }}
    >
      {text}
    </span>
  )
}

/** The one-time token, shown once; Done asks twice while it is uncopied. */
function TokenView({
  token,
  mode,
  onDone
}: {
  token: string | null
  mode: SolMode
  onDone: () => void
}): React.JSX.Element {
  const [copied, setCopied] = useState(false)
  const [copyFailed, setCopyFailed] = useState(false)
  const [armed, setArmed] = useState(false)
  const done = (): void => {
    if (copied || armed || !token) onDone()
    else setArmed(true)
  }
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.5 }}>
        {githubText('invite_shown', mode)}
      </div>
      <div
        data-testid="invite-token"
        style={{
          marginTop: 10,
          padding: '9px 11px',
          background: 'var(--bg)',
          border: '1px solid var(--bd)',
          borderRadius: 3,
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          wordBreak: 'break-all'
        }}
      >
        {token ?? 'The token was not returned. Revoke this invite and send a new one.'}
      </div>
      {copyFailed && (
        <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>
          Copy failed — select the token above and copy it by hand.
        </div>
      )}
      {armed && (
        <div role="alert" style={{ marginTop: 8, fontSize: 11.5, color: 'var(--warn)' }}>
          You won&apos;t see this token again. Copy it, or click Done once more to close anyway.
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
        {token && (
          <Button
            kind="ghost"
            size="sm"
            onClick={() =>
              void copyToClipboard(token).then((ok) => {
                setCopied(ok)
                setCopyFailed(!ok)
              })
            }
          >
            {copied ? 'Copied' : 'Copy token'}
          </Button>
        )}
        <Button kind="primary" size="sm" onClick={done}>
          Done
        </Button>
      </div>
    </div>
  )
}

const markInvited = (members: readonly GithubOrgMember[], githubId: number): GithubOrgMember[] =>
  members.map((m) => (m.github_id === githubId ? { ...m, solus_status: 'invited' } : m))

interface RosterState {
  members: GithubOrgMember[]
  cursor: string | null
  loading: boolean
  loadFailed: boolean
  problem: Problem | null
  inviting: number | null
  token: { value: string | null } | null
  loadMore: () => void
  invite: (member: GithubOrgMember) => Promise<void>
  dismissToken: () => void
}

function useRoster(actions: GitHubRosterModalProps['actions'], mode: SolMode): RosterState {
  const [members, setMembers] = useState<GithubOrgMember[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [inviting, setInviting] = useState<number | null>(null)
  const [token, setToken] = useState<{ value: string | null } | null>(null)
  // `actions` is rebuilt every render by the hook; always call the latest.
  const latest = useRef(actions)
  latest.current = actions

  const loadPage = useCallback(async (after?: string): Promise<void> => {
    setLoading(true)
    setLoadFailed(false)
    const page = await latest.current.loadRoster(after)
    setLoading(false)
    if (!page.ok) {
      setLoadFailed(true)
      return
    }
    setMembers((prev) => (after ? [...prev, ...page.items] : page.items))
    setCursor(page.cursor)
  }, [])

  useEffect(() => {
    void loadPage()
  }, [loadPage])

  const invite = async (member: GithubOrgMember): Promise<void> => {
    setInviting(member.github_id)
    setProblem(null)
    const outcome = await latest.current.inviteMember(member)
    setInviting(null)
    if (outcome.ok) {
      setMembers((prev) => markInvited(prev, member.github_id))
      setToken({ value: outcome.token })
    } else if (outcome.reason === 'plan_limit') {
      setProblem({ kind: 'limit', message: outcome.limit.message })
    } else {
      const key = outcome.reason === 'not_an_org_member' ? 'not_an_org_member' : 'invite_failed'
      setProblem({ kind: 'text', text: githubText(key, mode) })
    }
  }

  return {
    members,
    cursor,
    loading,
    loadFailed,
    problem,
    inviting,
    token,
    loadMore: () => cursor && void loadPage(cursor),
    invite,
    dismissToken: () => setToken(null)
  }
}

function ErrorLine({ text }: { text: string }): React.JSX.Element {
  return (
    <div role="alert" style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>
      {text}
    </div>
  )
}

function RosterList({ roster, mode }: { roster: RosterState; mode: SolMode }): React.JSX.Element {
  const empty = !roster.loading && !roster.loadFailed && roster.members.length === 0
  return (
    <div style={{ marginTop: 12, maxHeight: 320, overflowY: 'auto' }}>
      {roster.members.map((m) => (
        <Row
          key={m.github_id}
          member={m}
          busy={roster.inviting !== null}
          onInvite={(x) => void roster.invite(x)}
        />
      ))}
      {roster.loading && <Spinner size={14} />}
      {empty && (
        <div style={{ fontSize: 12, color: 'var(--mut)' }}>{githubText('roster_empty', mode)}</div>
      )}
    </div>
  )
}

export function GitHubRosterModal({
  actions,
  login,
  onClose,
  onUpgrade
}: GitHubRosterModalProps): React.JSX.Element {
  const mode = useSettingsStore((s) => s.solMode)
  const roster = useRoster(actions, mode)
  const { problem } = roster
  return (
    <ModalShell onClose={onClose} width={420}>
      <div role="dialog" aria-modal="true" aria-label={`Members of ${login} on GitHub`}>
        <div style={{ fontSize: 16, fontWeight: 600, wordBreak: 'break-all' }}>
          Members of {login} on GitHub
        </div>
        {roster.token ? (
          <TokenView token={roster.token.value} mode={mode} onDone={roster.dismissToken} />
        ) : (
          <>
            <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 4, lineHeight: 1.5 }}>
              {githubText('roster_intro', mode)}
            </div>
            <RosterList roster={roster} mode={mode} />
            {roster.loadFailed && <ErrorLine text={githubText('roster_failed', mode)} />}
            {problem?.kind === 'text' && <ErrorLine text={problem.text} />}
            {problem?.kind === 'limit' && (
              <PlanLimitNotice message={problem.message} onUpgrade={onUpgrade} />
            )}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
              {roster.cursor && !roster.loading && (
                <Button kind="ghost" size="sm" onClick={roster.loadMore}>
                  Load more
                </Button>
              )}
              <Button kind="primary" size="sm" onClick={onClose}>
                Close
              </Button>
            </div>
          </>
        )}
      </div>
    </ModalShell>
  )
}
