// SOLUSDEV-317: one row of GITHUB ORG MEMBERS — avatar (https only), @login
// (text, never HTML), a status chip, and the admin controls: Assign / Change
// (one picker), Unassign (confirmed inline), Invite on `not_on_solus` rows.
// Verified rows have no control. Each row owns its pending state, its error
// (role=alert) and its announcement (role=status); other rows never block.
import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { relativeTime } from '../../lib/relativeTime'
import type { GithubOrgMember } from '../../lib/api/resources.teamGithub'
import type { SolMode } from '../../store/settingsStore'
import { AssignPicker } from './AssignPicker'
import { safeHttpsUrl } from './githubInstallFlow'
import { githubText } from './githubOrgCopy'
import { rowKind, type PickerOption, type RowKind } from './githubOrgMembersView'
import type { RowProblem } from './githubOrgRoster'
import { homeStagger } from './homeMotion'
import { PlanLimitNotice } from './PlanLimitNotice'
import type { RowState } from './useGithubOrgRoster'

export interface GitHubOrgMemberRowProps {
  member: GithubOrgMember
  index: number
  state: RowState | undefined
  options: readonly PickerOption[]
  mode: SolMode
  onAssign: (userId: string) => void
  onUnassign: () => void
  onInvite: () => void
  onFind: (login: string) => void
  onUpgrade?: () => void
}

const CHIP: Record<RowKind, { text: string; color: string }> = {
  verified: { text: 'Verified', color: 'var(--ok)' },
  assigned: { text: 'Assigned', color: 'var(--acc)' },
  invited: { text: 'Invited', color: 'var(--warn)' },
  not_on_solus: { text: 'Not on Solus', color: 'var(--mut)' }
}

const ROW: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 11,
  padding: '10px 14px',
  borderBottom: '1px solid var(--bd)',
  flexWrap: 'wrap'
}

export function GitHubOrgMemberRow(props: GitHubOrgMemberRowProps): React.JSX.Element {
  const { member, index, state, mode } = props
  const kind = rowKind(member)
  return (
    <li
      aria-label={`@${member.github_login}`}
      className="home-row-in"
      style={{ ...homeStagger(index), ...ROW }}
    >
      <OrgAvatar url={member.avatar_url} />
      <div style={{ flex: '1 1 200px', minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12.5, fontWeight: 600, wordBreak: 'break-all' }}>
            @{member.github_login}
          </span>
          <Chip
            kind={kind}
            title={kind === 'verified' ? githubText('verified_hint', mode) : undefined}
          />
        </div>
        <Assignee member={member} kind={kind} mode={mode} />
      </div>
      {kind !== 'verified' && <Controls {...props} kind={kind} />}
      <RowFeedback {...props} problem={state?.error ?? null} />
    </li>
  )
}

function OrgAvatar({ url }: { url: string | null }): React.JSX.Element {
  const src = safeHttpsUrl(url)
  return (
    <span
      aria-hidden
      style={{
        width: 26,
        height: 26,
        borderRadius: 13,
        overflow: 'hidden',
        background: 'var(--sur2)',
        border: '1px solid var(--bd)',
        flexShrink: 0
      }}
    >
      {src && (
        <img src={src} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
      )}
    </span>
  )
}

function Chip({ kind, title }: { kind: RowKind; title?: string }): React.JSX.Element {
  const chip = CHIP[kind]
  return (
    <span
      title={title}
      style={{
        border: `1px solid ${chip.color}`,
        color: chip.color,
        borderRadius: 3,
        padding: '1px 6px',
        lineHeight: 1.4
      }}
    >
      <Mono size={9} color={chip.color}>
        {chip.text}
      </Mono>
    </span>
  )
}

function Assignee({
  member,
  kind,
  mode
}: {
  member: GithubOrgMember
  kind: RowKind
  mode: SolMode
}): React.JSX.Element | null {
  const a = member.assignment
  if (!a) return null
  const by =
    a.assigned_by && a.assigned_at
      ? githubText('assigned_by', mode, {
          by: a.assigned_by.name ?? githubText('former_member', mode),
          when: relativeTime(a.assigned_at)
        })
      : null
  return (
    <div style={{ marginTop: 3, fontSize: 11.5, color: 'var(--mut)', lineHeight: 1.5 }}>
      <span style={{ color: 'var(--tx)' }}>{a.name ?? a.email}</span>
      {by && <span> · {by}</span>}
      {kind === 'verified' && mode === 'Guide' && (
        <div style={{ fontSize: 11 }}>{githubText('verified_hint', mode)}</div>
      )}
    </div>
  )
}

function Controls({
  member,
  state,
  options,
  mode,
  kind,
  onAssign,
  onUnassign,
  onInvite
}: GitHubOrgMemberRowProps & { kind: RowKind }): React.JSX.Element {
  const [confirming, setConfirming] = useState(false)
  const pending = state?.pending ?? false
  const controlsRef = useRef<HTMLDivElement>(null)
  const refocus = useRef(false)
  useEffect(() => {
    if (confirming || !refocus.current) return
    refocus.current = false
    controlsRef.current?.querySelector<HTMLButtonElement>('button[aria-haspopup]')?.focus()
  }, [confirming])
  const endConfirm = (): void => {
    refocus.current = true
    setConfirming(false)
  }
  const login = member.github_login
  if (confirming && member.assignment) {
    const name = member.assignment.name ?? member.assignment.email
    return (
      <UnassignConfirm
        text={githubText('unassign_confirm', mode, { login, name })}
        onConfirm={() => {
          endConfirm()
          onUnassign()
        }}
        onCancel={endConfirm}
      />
    )
  }
  return (
    <div ref={controlsRef} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      {pending && <Spinner size={12} />}
      <AssignPicker
        label={kind === 'assigned' ? 'Change' : 'Assign'}
        listLabel={`Teammate for @${login}`}
        options={options}
        emptyText={githubText('no_teammates_left', mode)}
        onPick={onAssign}
      />
      {kind === 'assigned' && (
        <Button kind="ghost" size="sm" disabled={pending} onClick={() => setConfirming(true)}>
          Unassign
        </Button>
      )}
      {kind === 'not_on_solus' && (
        <Button
          kind="ghost"
          size="sm"
          disabled={pending}
          aria-label={`Invite @${login}`}
          onClick={onInvite}
        >
          Invite
        </Button>
      )}
    </div>
  )
}

function UnassignConfirm({
  text,
  onConfirm,
  onCancel
}: {
  text: string
  onConfirm: () => void
  onCancel: () => void
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
      <span style={{ fontSize: 11.5, color: 'var(--mut)', maxWidth: 320 }}>{text}</span>
      <Button kind="danger" size="sm" aria-label="Confirm unassign" autoFocus onClick={onConfirm}>
        Unassign
      </Button>
      <Button kind="ghost" size="sm" onClick={onCancel}>
        Cancel
      </Button>
    </div>
  )
}

/** The row's live region (always mounted, so a later announcement is read)
 *  and, under it, its error — a plan limit gets the Upgrade path. */
function RowFeedback({
  state,
  mode,
  problem,
  onFind,
  onUpgrade
}: GitHubOrgMemberRowProps & { problem: RowProblem | null }): React.JSX.Element {
  const announce = state?.announce
  return (
    <div style={{ flexBasis: '100%', paddingLeft: 37 }}>
      <div role="status" style={{ fontSize: 11, color: 'var(--ok)' }}>
        {announce ? githubText(announce.key, mode, announce.vars) : ''}
      </div>
      {problem && 'limit' in problem && (
        <PlanLimitNotice message={problem.limit} onUpgrade={onUpgrade} />
      )}
      {problem && 'key' in problem && (
        <ProblemLine
          text={githubText(problem.key, mode, problem.vars)}
          other={problem.vars.other}
          onFind={onFind}
        />
      )}
    </div>
  )
}

function ProblemLine({
  text,
  other,
  onFind
}: {
  text: string
  other: string | undefined
  onFind: (login: string) => void
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <span role="alert" style={{ fontSize: 11.5, color: 'var(--err)', lineHeight: 1.5 }}>
        {text}
      </span>
      {other && other !== '?' && (
        <Button kind="bare" size="sm" onClick={() => onFind(other)}>
          Find @{other}
        </Button>
      )}
    </div>
  )
}
