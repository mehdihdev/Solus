// The destructive-action approval surface (SOLUSDEV-96 / ONS-UI-01).
//
// GENERIC ACROSS TOOLS by construction — it renders `{label, before, after}`
// rows and knows nothing about Onshape. A CAD edit, a firmware flash, a robot
// move and a shell command all arrive in this shape and all render here, which
// is why no copy on this card names a domain.
//
// It shows the DIFF, not just the action name: approving "onshape.set_variable"
// tells a user nothing, and the whole server-side-args design exists so what is
// displayed is what runs. A tool with no before/after still gets rows — the
// server falls back to the arguments it will execute with.
//
// Values render WITHOUT the mono style's uppercasing: an Onshape variable name
// and a FeatureScript unit token are case-sensitive, so `#WIDTH * 2` is simply
// not the expression being approved.
//
// The card owns FAILURE only. On success its host removes it; keeping a
// "done" state here would be dead code that hides whether anything ran.
import { useCallback, useState } from 'react'
import { Mono } from '../../components/ui/Mono'
import type { ConfirmationRow, PendingConfirmation } from '../../lib/api/solStream'
import './ConfirmationCard.css'
import { CommandOutput } from './CommandOutput'

/** Mono uppercases by default; a value being approved must render exactly as it
 *  will execute. */
const VERBATIM = { textTransform: 'none' } as const

export type ConfirmationDecision = 'approve' | 'reject'

export interface ConfirmationCardProps {
  readonly projectId?: string
  readonly pending: PendingConfirmation
  /** Resolves once the decision is recorded. Rejection is a decision too. */
  readonly onDecide: (decision: ConfirmationDecision) => Promise<void>
}

function DiffValue({ value }: { value: string | null }): React.JSX.Element {
  return (
    <span className="confirmation-card__value">
      {value === null ? (
        <em className="confirmation-card__empty">Not provided</em>
      ) : value === '' ? (
        <em className="confirmation-card__empty">Empty string</em>
      ) : (
        value
      )}
    </span>
  )
}

function DiffRow({ row }: { row: ConfirmationRow }): React.JSX.Element {
  return (
    <li className="confirmation-card__change">
      <strong className="confirmation-card__label">{row.label}</strong>
      <dl className="confirmation-card__comparison">
        <div className="confirmation-card__before">
          <dt>Before</dt>
          <dd>
            <DiffValue value={row.before} />
          </dd>
        </div>
        <div className="confirmation-card__after">
          <dt>After</dt>
          <dd>
            <DiffValue value={row.after} />
          </dd>
        </div>
      </dl>
    </li>
  )
}

function CompletePreview({ rows }: { rows: readonly ConfirmationRow[] }): React.JSX.Element {
  const brief =
    rows.length <= 2 &&
    rows.every((row) =>
      [row.label, row.before, row.after].every(
        (value) => value === null || (value.length <= 160 && !value.includes('\n'))
      )
    )
  return (
    <details className="confirmation-card__preview" open={brief}>
      <summary>
        {rows.length === 1 ? 'Review 1 change' : `Review all ${rows.length} changes`}
      </summary>
      <div
        className="confirmation-card__scroll"
        role="region"
        aria-label="Complete proposed changes"
        tabIndex={0}
      >
        <ul aria-label="Proposed changes" className="confirmation-card__changes">
          {rows.map((row, index) => (
            <DiffRow key={`${row.label}-${index}`} row={row} />
          ))}
        </ul>
      </div>
    </details>
  )
}

/** Why a decision did not go through, and whether it can be tried again.
 *
 *  TWO kinds, and conflating them is its own bug: a TRANSPORT failure leaves the
 *  action genuinely parked, while a server REFUSAL is terminal — the row can
 *  never be approved again, so "still waiting" would be false. */
function DecisionFailure({
  failed
}: {
  failed: { message: string; terminal: boolean }
}): React.JSX.Element {
  return (
    <Mono
      style={{ ...VERBATIM, color: failed.terminal ? 'var(--err)' : 'var(--acc)' }}
      data-terminal={failed.terminal ? 'true' : 'false'}
    >
      {failed.message}{' '}
      {failed.terminal
        ? // Deliberately claims nothing about what RAN: a tool that failed after
          // approval may have partly executed, so "nothing was applied" would be
          // its own lie. This sentence is true in every terminal case.
          'This approval can’t be retried — ask SOL again if you still want it.'
        : 'The action is still waiting for you.'}
    </Mono>
  )
}

function approvalStatus(closed: boolean, busy: boolean): string {
  if (closed) return 'Approval closed'
  return busy ? 'Recording decision…' : 'Awaiting approval'
}

function ActiveCommandOutput({
  busy,
  projectId,
  pending
}: {
  busy: ConfirmationDecision | null
  projectId: string | undefined
  pending: PendingConfirmation
}): React.JSX.Element | null {
  if (busy !== 'approve' || !projectId || !['code.run', 'code.test'].includes(pending.tool))
    return null
  return (
    <CommandOutput
      key={pending.confirmationId}
      projectId={projectId}
      confirmationId={pending.confirmationId}
    />
  )
}

export function ConfirmationCard({
  pending,
  onDecide,
  projectId
}: ConfirmationCardProps): React.JSX.Element {
  const { busy, failed, decide } = useConfirmationDecision(onDecide)

  return (
    <section aria-label="Action needs your approval" className="confirmation-card">
      <header className="confirmation-card__header">
        <h3>Review this action</h3>
        <span className="confirmation-card__status">
          {approvalStatus(failed?.terminal === true, busy !== null)}
        </span>
      </header>

      <p className="confirmation-card__summary">{pending.summary}</p>

      <div className="confirmation-card__actions">
        <button
          className="confirmation-card__approve"
          type="button"
          onClick={() => void decide('approve')}
          disabled={busy !== null || failed?.terminal === true}
        >
          {busy === 'approve' ? 'Applying…' : 'Approve'}
        </button>
        <button
          type="button"
          onClick={() => void decide('reject')}
          disabled={busy !== null || failed?.terminal === true}
        >
          Reject
        </button>
      </div>

      {pending.preview.length > 0 ? (
        <CompletePreview rows={pending.preview} />
      ) : (
        <Mono style={{ color: 'var(--mut)' }}>
          This tool could not describe its change — review the action above before approving.
        </Mono>
      )}

      <ConfirmationDetails pending={pending} />

      {failed !== null && (
        <div role="alert">
          <DecisionFailure failed={failed} />
        </div>
      )}
      <ActiveCommandOutput busy={busy} projectId={projectId} pending={pending} />
    </section>
  )
}

function ConfirmationDetails({ pending }: { pending: PendingConfirmation }): React.JSX.Element {
  return (
    <details className="confirmation-card__details">
      <summary>Technical details</summary>
      <dl>
        <div>
          <dt>Tool</dt>
          <dd>{pending.tool}</dd>
        </div>
        <div>
          <dt>Approval ID</dt>
          <dd>{pending.confirmationId}</dd>
        </div>
      </dl>
    </details>
  )
}

function useConfirmationDecision(onDecide: ConfirmationCardProps['onDecide']): {
  busy: ConfirmationDecision | null
  failed: { message: string; terminal: boolean } | null
  decide: (decision: ConfirmationDecision) => Promise<void>
} {
  const [busy, setBusy] = useState<ConfirmationDecision | null>(null)
  const [failed, setFailed] = useState<{ message: string; terminal: boolean } | null>(null)

  // useCallback so react-hooks can see this is an event handler rather than
  // effect-adjacent state writing.
  const decide = useCallback(
    async (decision: ConfirmationDecision): Promise<void> => {
      setBusy(decision)
      setFailed(null)
      try {
        await onDecide(decision)
        // Success: the host removes this card. Nothing to render here, and a
        // local "applied" state would claim an outcome we cannot see.
      } catch (error) {
        // A failed decision must never look like a successful one. Show the
        // server's own reason — "expired", "already decided", "what this would
        // do has changed" are all different, and a generic apology hides which.
        //
        // TWO kinds, and conflating them is its own bug: a TRANSPORT failure
        // leaves the action genuinely parked and retryable, while a
        // ConfirmationRefused means the server decided and refused. Those rows
        // are TERMINAL — the confirmation can never be approved again — so
        // saying "still waiting" and leaving Approve live only earns "This
        // action was already …" on the next click.
        setFailed({
          message: error instanceof Error ? error.message : 'That didn’t go through.',
          // Checked by NAME, not `instanceof`: this error crosses a module
          // boundary, and a bundled or mocked second copy of the class would
          // make an identity check silently false — the failure mode being
          // fixed here, reintroduced one level down.
          terminal: error instanceof Error && error.name === 'ConfirmationRefused'
        })
      } finally {
        setBusy(null)
      }
    },
    [onDecide]
  )

  return { busy, failed, decide }
}
