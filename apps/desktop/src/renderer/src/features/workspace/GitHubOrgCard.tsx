// Home's GITHUB ORGANIZATION card (SOLUSDEV-216 / ADR-039, home.md). A team-owned
// GitHub App installation: link it once and everyone on the team can add the
// org's repos with no personal sign-in. Every state of the wireflow lives here:
// unlinked (admin / member), unconfigured, linking, requested, linked,
// suspended. Collaborative teams only — Home does not mount it on the personal
// team. Strings come from githubOrgCopy (Guide/Expert); anything the server or
// GitHub supplies (logins, URLs) is rendered as text, and URLs only when https.
// SOLUSDEV-317: the roster moved inline (GitHubOrgMembersSection); the card
// takes its state from TeamGithubPanel, which shares it with that section.
import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { relativeTime } from '../../lib/relativeTime'
import type { TeamInstallation } from '../../lib/api/resources.teamGithub'
import { useSettingsStore, type SolMode } from '../../store/settingsStore'
import { safeHttpsUrl } from './githubInstallFlow'
import { githubText, refusalCopyKey, type GithubCopyKey } from './githubOrgCopy'
import { ModalShell } from './modals'
import { PlanLimitNotice } from './PlanLimitNotice'
import type { LinkNotice, TeamGithub } from './useTeamGithub'

export interface GitHubOrgCardProps {
  github: TeamGithub
  /** The active team — the one a link always belongs to. */
  teamName: string
  /** Owner or admin: may link and unlink. */
  canManage: boolean
  onUpgrade?: () => void
}

const NOTE_STYLE: React.CSSProperties = { fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }

export function GitHubOrgCard({
  github,
  teamName,
  canManage,
  onUpgrade
}: GitHubOrgCardProps): React.JSX.Element {
  const mode = useSettingsStore((s) => s.solMode)
  // The unlink dialog lives HERE, not in the linked view: a successful unlink
  // refetches the card to "unlinked", which must not tear the dialog down before
  // it offers "Uninstall on GitHub".
  const [unlinking, setUnlinking] = useState(false)
  return (
    <div style={{ minWidth: 0 }} data-testid="github-org-card">
      <div style={{ margin: '0 0 10px' }}>
        <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
          GITHUB ORGANIZATION
        </Mono>
      </div>
      <Card pad={16}>
        <CardBody
          github={github}
          teamName={teamName}
          mode={mode}
          canManage={canManage}
          onUpgrade={onUpgrade}
          onUnlink={() => setUnlinking(true)}
        />
      </Card>
      {unlinking && <UnlinkModal github={github} mode={mode} onClose={() => setUnlinking(false)} />}
    </div>
  )
}

interface BodyProps {
  github: TeamGithub
  teamName: string
  mode: SolMode
  canManage: boolean
  onUpgrade?: () => void
  onUnlink: () => void
}

function CardBody({
  github,
  teamName,
  mode,
  canManage,
  onUpgrade,
  onUnlink
}: BodyProps): React.JSX.Element | null {
  if (github.status === 'idle') return null
  if (github.status === 'loading') return <Spinner size={14} />
  if (github.status === 'offline') return <OfflineNote github={github} mode={mode} />
  if (github.unconfigured) return <div style={NOTE_STYLE}>{githubText('unconfigured', mode)}</div>
  if (github.installation) {
    return (
      <LinkedView
        github={github}
        installation={github.installation}
        mode={mode}
        canManage={canManage}
        onUnlink={onUnlink}
      />
    )
  }
  return (
    <UnlinkedView
      github={github}
      teamName={teamName}
      mode={mode}
      canManage={canManage}
      onUpgrade={onUpgrade}
      onUnlink={onUnlink}
    />
  )
}

function OfflineNote({ github, mode }: { github: TeamGithub; mode: SolMode }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      <div role="status" style={NOTE_STYLE}>
        {githubText('offline_note', mode)}
      </div>
      <Button kind="ghost" size="sm" onClick={() => void github.actions.refresh()}>
        Retry
      </Button>
    </div>
  )
}

function UnlinkedView({
  github,
  teamName,
  mode,
  canManage,
  onUpgrade
}: BodyProps): React.JSX.Element {
  const { linking, notice } = github
  const requested = notice?.kind === 'requested'
  return (
    <div>
      {canManage && <LinkTarget teamName={teamName} mode={mode} />}
      <div style={NOTE_STYLE}>
        {linking
          ? githubText('linking', mode)
          : requested
            ? githubText('requested', mode)
            : githubText(canManage ? 'unlinked_admin' : 'unlinked_member', mode)}
      </div>
      {canManage && (
        <div style={{ marginTop: 12 }}>
          <Button
            kind="primary"
            size="sm"
            disabled={linking}
            onClick={() => void github.actions.link()}
          >
            {linking ? 'Waiting for GitHub…' : 'Link organization'}
          </Button>
        </div>
      )}
      {notice && <NoticeLine notice={notice} mode={mode} onUpgrade={onUpgrade} />}
    </div>
  )
}

/** "Link a GitHub organization to <team>" — the link always belongs to the team
 *  in the sidebar switcher. The team name is text, never HTML. */
function LinkTarget({ teamName, mode }: { teamName: string; mode: SolMode }): React.JSX.Element {
  const slot = '\u0000'
  const [before, after = ''] = githubText('link_target', mode, { team: slot }).split(slot)
  return (
    <div style={{ fontSize: 13, marginBottom: 6 }}>
      {before}
      <strong style={{ wordBreak: 'break-all' }}>{teamName}</strong>
      {after}
    </div>
  )
}

function noticeKey(notice: LinkNotice): GithubCopyKey | null {
  switch (notice.kind) {
    case 'requested':
      return null
    case 'cancelled':
      return 'cancelled'
    case 'refused':
      return refusalCopyKey(notice.code) ?? 'failed'
    case 'failed':
      return notice.reason === 'no_bridge' ? 'no_bridge' : 'failed'
  }
}

function NoticeLine({
  notice,
  mode,
  onUpgrade
}: {
  notice: LinkNotice
  mode: SolMode
  onUpgrade?: () => void
}): React.JSX.Element | null {
  if (notice.kind === 'refused' && notice.code === 'plan_limit_reached') {
    const message = notice.limit?.message ?? githubText('plan_limit_reached', mode)
    return <PlanLimitNotice message={message} onUpgrade={onUpgrade} />
  }
  const key = noticeKey(notice)
  if (!key) return null
  const detail = notice.kind === 'failed' ? notice.message : null
  return (
    <div
      role="alert"
      style={{ marginTop: 10, fontSize: 11.5, color: 'var(--err)', lineHeight: 1.5 }}
    >
      {detail ?? githubText(key, mode)}
    </div>
  )
}

function ExternalLink({
  href,
  label
}: {
  href: string | null
  label: string
}): React.JSX.Element | null {
  if (!href) return null
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        fontSize: 12,
        color: 'var(--tx)',
        textDecoration: 'none',
        border: '1px solid var(--bd)',
        borderRadius: 3,
        padding: '6px 12px'
      }}
    >
      {label}
      <Icons.external size={11} />
    </a>
  )
}

function Avatar({ url }: { url: string | null }): React.JSX.Element {
  const src = safeHttpsUrl(url)
  return (
    <span
      aria-hidden
      style={{
        width: 28,
        height: 28,
        borderRadius: 6,
        background: 'var(--sur2)',
        border: '1px solid var(--bd)',
        overflow: 'hidden',
        flexShrink: 0
      }}
    >
      {src && (
        <img src={src} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
      )}
    </span>
  )
}

function repoCountText(count: number | null): string | null {
  if (count === null) return null
  return `${count} ${count === 1 ? 'repo' : 'repos'}`
}

function LinkedView({
  github,
  installation,
  mode,
  canManage,
  onUnlink
}: {
  github: TeamGithub
  installation: TeamInstallation
  mode: SolMode
  canManage: boolean
  onUnlink: () => void
}): React.JSX.Element {
  const count = repoCountText(github.repoCount)
  const linkedBy = installation.linked_by?.name ?? githubText('former_member', mode)
  const scope = githubText(
    installation.repository_selection === 'all' ? 'scope_all' : 'scope_selected',
    mode
  )
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <Avatar url={installation.account_avatar_url} />
        <div style={{ minWidth: 0, fontSize: 12.5 }}>
          <span style={{ fontWeight: 600, wordBreak: 'break-all' }}>
            {installation.account_login}
          </span>
          <span style={{ color: 'var(--mut)' }}>
            {' · '}
            {installation.account_type}
            {count ? ` · ${count}` : ''}
          </span>
        </div>
      </div>
      <div style={{ ...NOTE_STYLE, marginTop: 8, fontSize: 11.5 }}>
        {githubText('linked_by', mode, {
          by: linkedBy,
          when: relativeTime(installation.linked_at),
          scope
        })}
      </div>
      {installation.status === 'suspended' && (
        <div
          role="status"
          style={{ marginTop: 8, fontSize: 11.5, color: 'var(--warn)', lineHeight: 1.5 }}
        >
          {githubText('suspended', mode)}
        </div>
      )}
      <div
        style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12, flexWrap: 'wrap' }}
      >
        <ExternalLink href={safeHttpsUrl(installation.manage_url)} label="Manage on GitHub" />
        {canManage && <OverflowMenu onUnlink={onUnlink} />}
      </div>
    </div>
  )
}

/** A disclosure (not an ARIA menu): the trigger exposes aria-expanded /
 *  aria-controls, Escape or a click/Tab away closes it, and Escape returns focus
 *  to the trigger. Choosing Unlink also parks focus on the trigger so the dialog
 *  it opens restores focus somewhere real. */
function OverflowMenu({ onUnlink }: { onUnlink: () => void }): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const rootRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent): void => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [open])

  const closeToTrigger = (): void => {
    setOpen(false)
    rootRef.current?.querySelector<HTMLButtonElement>('[aria-controls]')?.focus()
  }

  return (
    <span
      ref={rootRef}
      style={{ position: 'relative' }}
      onKeyDown={(event) => {
        if (open && event.key === 'Escape') {
          event.stopPropagation()
          closeToTrigger()
        }
      }}
      onBlur={(event) => {
        const next = event.relatedTarget
        if (open && next instanceof Node && !rootRef.current?.contains(next)) setOpen(false)
      }}
    >
      <Button
        kind="bare"
        size="sm"
        aria-label="More actions"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        ⋯
      </Button>
      {open && (
        <div
          id={panelId}
          style={{
            position: 'absolute',
            right: 0,
            top: '100%',
            zIndex: 20,
            background: 'var(--sur)',
            border: '1px solid var(--bd)',
            borderRadius: 4,
            minWidth: 120
          }}
        >
          <button
            type="button"
            onClick={() => {
              closeToTrigger()
              onUnlink()
            }}
            className="interactive"
            style={{
              display: 'block',
              width: '100%',
              textAlign: 'left',
              padding: '8px 12px',
              fontSize: 12.5,
              color: 'var(--err)',
              background: 'transparent',
              border: 'none',
              cursor: 'pointer'
            }}
          >
            Unlink
          </button>
        </div>
      )}
    </span>
  )
}

type UnlinkStep =
  | { phase: 'confirm'; busy: boolean; failed: boolean }
  | { phase: 'done'; sources: number; manageUrl: string }

function UnlinkModal({
  github,
  mode,
  onClose
}: {
  github: TeamGithub
  mode: SolMode
  onClose: () => void
}): React.JSX.Element {
  const [step, setStep] = useState<UnlinkStep>({ phase: 'confirm', busy: false, failed: false })
  const unlink = async (): Promise<void> => {
    setStep({ phase: 'confirm', busy: true, failed: false })
    const outcome = await github.actions.unlink()
    setStep(
      outcome.ok
        ? { phase: 'done', sources: outcome.disabledSources, manageUrl: outcome.manageUrl }
        : { phase: 'confirm', busy: false, failed: true }
    )
  }
  const titleId = useId()
  return (
    <ModalShell onClose={onClose} width={400} labelledBy={titleId} closeOnEscape>
      <div>
        <div id={titleId} style={{ fontSize: 16, fontWeight: 600 }}>
          Unlink GitHub organization
        </div>
        {step.phase === 'confirm' ? (
          <>
            <div style={{ ...NOTE_STYLE, marginTop: 8 }}>
              {typeof github.installation?.bound_source_count === 'number'
                ? githubText('unlink_confirm_count', mode, {
                    n: github.installation.bound_source_count
                  })
                : githubText('unlink_confirm', mode)}
            </div>
            {step.failed && (
              <div role="alert" style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>
                {githubText('unlink_failed', mode)}
              </div>
            )}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
              <Button kind="ghost" size="sm" onClick={onClose}>
                Cancel
              </Button>
              <Button kind="danger" size="sm" disabled={step.busy} onClick={() => void unlink()}>
                Unlink
              </Button>
            </div>
          </>
        ) : (
          <>
            <div style={{ ...NOTE_STYLE, marginTop: 8 }}>
              {githubText('unlink_done', mode, { n: step.sources })}
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
              <ExternalLink href={safeHttpsUrl(step.manageUrl)} label="Uninstall on GitHub" />
              <Button kind="primary" size="sm" onClick={onClose}>
                Done
              </Button>
            </div>
          </>
        )}
      </div>
    </ModalShell>
  )
}
