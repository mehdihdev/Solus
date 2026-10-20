// Home's GITHUB ORGANIZATION card (SOLUSDEV-216 / ADR-039, home.md). A team-owned
// GitHub App installation: link it once and everyone on the team can add the
// org's repos with no personal sign-in. Every state of the wireflow lives here:
// unlinked (admin / member), unconfigured, linking, requested, linked,
// suspended. Collaborative teams only — Home does not mount it on the personal
// team. Strings come from githubOrgCopy (Guide/Expert); anything the server or
// GitHub supplies (logins, URLs) is rendered as text, and URLs only when https.
// SOLUSDEV-317 (design A): a compact STRIP above the People table (`strip`),
// or setup step 2 on a solo team (`step`). State comes from TeamInvitesView,
// which shares one useTeamGithub with the roster.
import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
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
  /** `strip` (default): one row above the People table. `step`: the solo team's
   *  "2 · Link a GitHub organization" card. */
  variant?: 'strip' | 'step'
}

const BOX: React.CSSProperties = {
  minWidth: 0,
  border: '1px solid var(--bd)',
  borderRadius: 4,
  background: 'var(--sur)'
}

const NOTE_STYLE: React.CSSProperties = { fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }

export function GitHubOrgCard({
  github,
  teamName,
  canManage,
  onUpgrade,
  variant = 'strip'
}: GitHubOrgCardProps): React.JSX.Element {
  const mode = useSettingsStore((s) => s.solMode)
  // The unlink dialog lives HERE, not in the linked view: a successful unlink
  // refetches the card to "unlinked", which must not tear the dialog down before
  // it offers "Uninstall on GitHub".
  const [unlinking, setUnlinking] = useState(false)
  const step = variant === 'step'
  return (
    <section
      aria-label="GitHub organization"
      data-testid="github-org-card"
      data-variant={variant}
      style={{ ...BOX, padding: step ? 16 : '12px 16px' }}
    >
      {step && <StepHeading teamName={teamName} mode={mode} />}
      <CardBody
        github={github}
        teamName={teamName}
        mode={mode}
        canManage={canManage}
        onUpgrade={onUpgrade}
        onUnlink={() => setUnlinking(true)}
        step={step}
      />
      {unlinking && <UnlinkModal github={github} mode={mode} onClose={() => setUnlinking(false)} />}
    </section>
  )
}

/** Setup step 2's heading: a numbered badge and the link target. */
function StepHeading({ teamName, mode }: { teamName: string; mode: SolMode }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
      <StepBadge n={2} />
      <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>
        <LinkTarget teamName={teamName} mode={mode} />
      </h3>
    </div>
  )
}

export function StepBadge({
  n,
  active = false
}: {
  n: number
  active?: boolean
}): React.JSX.Element {
  const color = active ? 'var(--acc)' : 'var(--mut)'
  return (
    <span
      aria-hidden
      style={{
        width: 22,
        height: 22,
        flexShrink: 0,
        borderRadius: 99,
        border: `1px solid ${active ? 'var(--acc)' : 'var(--bd)'}`,
        color,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: 'var(--font-mono)',
        fontSize: 11
      }}
    >
      {n}
    </span>
  )
}

interface BodyProps {
  github: TeamGithub
  teamName: string
  mode: SolMode
  canManage: boolean
  onUpgrade?: () => void
  onUnlink: () => void
  step?: boolean
}

function CardBody({
  github,
  teamName,
  mode,
  canManage,
  onUpgrade,
  onUnlink,
  step = false
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
      step={step}
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

function unlinkedNote(github: TeamGithub, canManage: boolean): GithubCopyKey {
  if (github.linking) return 'linking'
  if (github.notice?.kind === 'requested') return 'requested'
  return canManage ? 'unlinked_admin' : 'unlinked_member'
}

/** Strip: mark · target + note · Link, in one wrapping row. Step: the note and
 *  Link under the step heading (which already names the target). */
function UnlinkedView({
  github,
  teamName,
  mode,
  canManage,
  onUpgrade,
  step
}: BodyProps): React.JSX.Element {
  const { linking, notice } = github
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        {!step && <GithubMark />}
        <div style={{ flex: '1 1 280px', minWidth: 0 }}>
          {canManage && !step && <LinkTarget teamName={teamName} mode={mode} />}
          <div style={NOTE_STYLE}>{githubText(unlinkedNote(github, canManage), mode)}</div>
        </div>
        {canManage && (
          <Button
            kind={step ? 'soft' : 'primary'}
            size="sm"
            disabled={linking}
            onClick={() => void github.actions.link()}
          >
            {linking ? 'Waiting for GitHub…' : 'Link organization'}
          </Button>
        )}
      </div>
      {notice && <NoticeLine notice={notice} mode={mode} onUpgrade={onUpgrade} />}
    </div>
  )
}

/** GitHub's mark, in the text colour (follows the theme). */
export function GithubMark({ size = 18 }: { size?: number }): React.JSX.Element {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="currentColor"
      style={{ flexShrink: 0 }}
    >
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  )
}

/** "Link a GitHub organization to <team>" — the link always belongs to the team
 *  in the sidebar switcher. The team name is text, never HTML. */
function LinkTarget({ teamName, mode }: { teamName: string; mode: SolMode }): React.JSX.Element {
  const slot = '\u0000'
  const [before, after = ''] = githubText('link_target', mode, { team: slot }).split(slot)
  return (
    <span style={{ display: 'block', fontSize: 13, marginBottom: 2 }}>
      {before}
      <strong style={{ wordBreak: 'break-all' }}>{teamName}</strong>
      {after}
    </span>
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
  const suspended = installation.status === 'suspended'
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Avatar url={installation.account_avatar_url} />
        <div style={{ flex: '1 1 280px', minWidth: 0, fontSize: 12.5 }}>
          <span style={{ fontWeight: 600, wordBreak: 'break-all' }}>
            {installation.account_login}
          </span>
          <span style={{ color: 'var(--mut)' }}>
            {' · '}
            {installation.account_type}
            {count ? ` · ${count}` : ''}
          </span>
          <div style={{ ...NOTE_STYLE, fontSize: 11.5 }}>
            {githubText('linked_by', mode, {
              by: linkedBy,
              when: relativeTime(installation.linked_at),
              scope
            })}
          </div>
        </div>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            letterSpacing: '0.06em',
            color: suspended ? 'var(--warn)' : 'var(--ok)'
          }}
        >
          ● {suspended ? 'SUSPENDED' : 'ACTIVE'}
        </span>
        <ExternalLink href={safeHttpsUrl(installation.manage_url)} label="Manage on GitHub" />
        {canManage && <OverflowMenu onUnlink={onUnlink} />}
      </div>
      {suspended && (
        <div
          role="status"
          style={{ marginTop: 8, fontSize: 11.5, color: 'var(--warn)', lineHeight: 1.5 }}
        >
          {githubText('suspended', mode)}
        </div>
      )}
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
