// SOLUSDEV-319: the command approval card, redesigned (design canvas
// "Command Approval Card Redesign"). ConfirmationCard owns the decision, the
// keyboard approver and the arming clock; this file only lays a command card
// out, in two variants:
//
// - `card` (SOL window and page): a status bar with the safety badges, the
//   command as one shell line with its working folder, the verbatim rows, and
//   a footer with Technical details, Reject and "Run command".
// - `pill` (the Ember Pill): the same content, rounder and roomier, SOL named
//   as the asker, and fluid motion (ConfirmationCard.css): the card rises in,
//   the orb breathes while it waits, the status cross-fades, and the buttons
//   respond to press. All of it stops under prefers-reduced-motion.
//
// Every value still renders as plain text. The verbatim rows stay open and in
// view — they are what the arming clock watches (§M1) — so the shell line is a
// summary of them, never a replacement.
import type { PendingConfirmation } from '../../lib/api/solStream'
import { commandLine, type CommandHeader } from './commandCard'

export type CommandCardVariant = 'card' | 'pill'

export interface CommandCardProps {
  readonly pending: PendingConfirmation
  readonly header: CommandHeader
  readonly variant: CommandCardVariant
  readonly busy: boolean
  readonly closed: boolean
  readonly shortcut: { readonly hint: string; readonly aria: string } | null
  readonly onApprove: () => void
  readonly onReject: () => void
  /** The verbatim rows (always open for a command). */
  readonly preview: React.ReactNode
  readonly details: React.ReactNode
  readonly failure: React.ReactNode
}

const COPY = {
  card: { waiting: 'Needs approval', run: 'Run command' },
  pill: { waiting: 'SOL wants to run a command', run: 'Run' }
} as const

function statusText(variant: CommandCardVariant, busy: boolean, closed: boolean): string {
  if (closed) return 'Approval closed'
  return busy ? 'Recording decision…' : COPY[variant].waiting
}

function LockIcon(): React.JSX.Element {
  return (
    <svg width="10" height="10" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="3" y="7" width="10" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  )
}

function folderName(cwd: string): string {
  return cwd.split('/').filter(Boolean).pop() ?? cwd
}

function Badges({ header }: { header: CommandHeader }): React.JSX.Element {
  return (
    <span className="cmd-card__badges">
      {header.sandboxed && (
        <span className="confirmation-card__badge" data-sandboxed="true">
          <LockIcon />
          sandboxed
        </span>
      )}
      {header.risks.map((risk) => (
        <span key={risk} className="confirmation-card__badge" data-risk={risk}>
          {risk}
        </span>
      ))}
    </span>
  )
}

function CommandSummary({
  pending,
  header
}: {
  pending: PendingConfirmation
  header: CommandHeader
}): React.JSX.Element {
  const { args, cwd } = commandLine(pending)
  return (
    <div className="cmd-card__command" role="group" aria-label="Command">
      <div className="cmd-card__line">
        <code className="cmd-card__code" aria-label="Command line">
          <span className="cmd-card__prompt-text" aria-hidden="true">
            $
          </span>
          {header.program !== null && (
            <span className="confirmation-card__program">{header.program}</span>
          )}
          {args !== null && args.length > 0 && <span> {args.join(' ')}</span>}
        </code>
        {cwd !== null && (
          <span className="cmd-card__cwd" title={cwd}>
            {folderName(cwd)}
          </span>
        )}
      </div>
      <Badges header={header} />
    </div>
  )
}

export function CommandCard(props: CommandCardProps): React.JSX.Element {
  const { pending, header, variant, busy, closed, shortcut } = props
  const spent = busy || closed
  const state = closed ? 'closed' : busy ? 'busy' : 'waiting'
  const status = statusText(variant, busy, closed)
  return (
    <section
      aria-label="Action needs your approval"
      className="confirmation-card cmd-card"
      data-variant={variant}
      data-state={state}
    >
      <header className="cmd-card__bar">
        <span className="cmd-card__signal" aria-hidden="true" />
        {/* Keyed so each new status fades in rather than snapping. */}
        <span key={status} className="cmd-card__status" role="status">
          {status}
        </span>
      </header>

      <CommandSummary pending={pending} header={header} />

      <p className="confirmation-card__summary">{pending.summary}</p>

      {props.preview}

      {props.failure}

      <div className="cmd-card__actions">
        {variant === 'card' && <div className="cmd-card__details">{props.details}</div>}
        <button
          type="button"
          className="cmd-card__reject"
          onClick={props.onReject}
          disabled={spent}
        >
          Reject
        </button>
        <button
          type="button"
          className="confirmation-card__approve cmd-card__run"
          onClick={props.onApprove}
          disabled={spent}
          aria-keyshortcuts={shortcut?.aria}
        >
          {busy ? 'Starting…' : COPY[variant].run}
          {shortcut && !busy && (
            <kbd className="confirmation-card__hint" aria-hidden="true">
              {shortcut.hint}
            </kbd>
          )}
        </button>
      </div>
      {variant === 'pill' && <div className="cmd-card__details">{props.details}</div>}
    </section>
  )
}
