// SOLUSDEV-317 (design A): the GITHUB cell of a teammate's row — their linked
// account (`@login`, verified / assigned by …), and for admins with a live
// Organization link: "Link GitHub…" when none, "Unlink" (confirmed inline) on
// an admin label. A verified link is read-only. A label, never access.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { relativeTime } from '../../lib/relativeTime'
import type { SolMode } from '../../store/settingsStore'
import { AssignPicker } from '../workspace/AssignPicker'
import { githubText } from '../workspace/githubOrgCopy'
import type { PickerOption } from '../workspace/githubOrgMembersView'
import type { RowState } from '../workspace/useGithubOrgRoster'
import type { MemberLink } from './rosterModel'
import { RowFeedback } from './RowFeedback'

export interface MemberGithubCellProps {
  name: string
  link: MemberLink | null
  /** Admin with a live Organization link: may link / unlink. */
  canLink: boolean
  options: readonly PickerOption[]
  rows: Readonly<Record<number, RowState>>
  mode: SolMode
  onLink: (githubId: number) => void
  onUnlink: (githubId: number) => void
  onFind: (login: string) => void
}

export function MemberGithubCell(props: MemberGithubCellProps): React.JSX.Element {
  const { link, canLink, rows, mode } = props
  // Feedback follows the account this row last acted on (assignments are by GitHub id).
  const [acted, setActed] = useState<number | null>(null)
  const state = acted === null ? undefined : rows[acted]
  const act = (githubId: number, run: (id: number) => void): void => {
    setActed(githubId)
    run(githubId)
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {state?.pending && <Spinner size={11} />}
        {link ? <LinkLabel link={link} mode={mode} /> : <NoLink />}
        {canLink && link?.source === 'admin' && (
          <UnlinkControl {...props} link={link} onConfirm={(id) => act(id, props.onUnlink)} />
        )}
        {canLink && !link && (
          <AssignPicker
            label="Link GitHub…"
            listLabel={`GitHub account for ${props.name}`}
            options={props.options}
            emptyText={githubText('no_org_members_left', mode)}
            onPick={(id) => act(Number(id), props.onLink)}
          />
        )}
      </div>
      <RowFeedback state={state} mode={mode} onFind={props.onFind} />
    </div>
  )
}

function LinkLabel({ link, mode }: { link: MemberLink; mode: SolMode }): React.JSX.Element {
  const verified = link.source === 'verified'
  const by =
    link.assignedBy && link.assignedAt
      ? githubText('assigned_by', mode, {
          by: link.assignedBy,
          when: relativeTime(link.assignedAt)
        })
      : null
  return (
    <span
      style={{ display: 'inline-flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}
      title={verified ? githubText('verified_hint', mode) : undefined}
    >
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, wordBreak: 'break-all' }}>
        @{link.login}
      </span>
      <Mono size={9} color={verified ? 'var(--ok)' : 'var(--mut)'}>
        {verified ? 'VERIFIED' : 'ASSIGNED'}
      </Mono>
      {by && <span style={{ fontSize: 10.5, color: 'var(--mut)' }}>{by}</span>}
    </span>
  )
}

function NoLink(): React.JSX.Element {
  return <span style={{ fontSize: 11.5, color: 'var(--mut)' }}>No GitHub linked</span>
}

function UnlinkControl({
  name,
  link,
  mode,
  onConfirm
}: Pick<MemberGithubCellProps, 'name' | 'mode'> & {
  link: MemberLink
  onConfirm: (githubId: number) => void
}): React.JSX.Element {
  const [confirming, setConfirming] = useState(false)
  if (!confirming) {
    return (
      <Button
        kind="bare"
        size="sm"
        aria-label={`Unlink @${link.login}`}
        onClick={() => setConfirming(true)}
      >
        Unlink
      </Button>
    )
  }
  return (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
      <span style={{ fontSize: 11.5, color: 'var(--mut)', maxWidth: 300 }}>
        {githubText('unassign_confirm', mode, { login: link.login, name })}
      </span>
      <Button
        kind="danger"
        size="sm"
        aria-label="Confirm unlink"
        autoFocus
        onClick={() => {
          setConfirming(false)
          onConfirm(link.githubId)
        }}
      >
        Unlink
      </Button>
      <Button kind="ghost" size="sm" onClick={() => setConfirming(false)}>
        Cancel
      </Button>
    </span>
  )
}
