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

/** Mono uppercases by default; a value being approved must render exactly as it
 *  will execute. */
const VERBATIM = { textTransform: 'none' } as const

export type ConfirmationDecision = 'approve' | 'reject'

export interface ConfirmationCardProps {
  readonly pending: PendingConfirmation
  /** Resolves once the decision is recorded. Rejection is a decision too. */
  readonly onDecide: (decision: ConfirmationDecision) => Promise<void>
}

function DiffRow({ row }: { row: ConfirmationRow }): React.JSX.Element {
  return (
    <li style={{ display: 'flex', gap: 8, alignItems: 'baseline', padding: '2px 0' }}>
      <Mono style={{ ...VERBATIM, color: 'var(--mut)', minWidth: 0, flex: '0 1 40%' }}>
        {row.label}
      </Mono>
      {row.before !== null && (
        <>
          <Mono style={{ ...VERBATIM, textDecoration: 'line-through', color: 'var(--mut)' }}>
            {row.before}
          </Mono>
          <span aria-hidden style={{ color: 'var(--mut)' }}>
            →
          </span>
        </>
      )}
      <Mono style={{ ...VERBATIM, color: 'var(--acc)' }}>{row.after ?? '—'}</Mono>
    </li>
  )
}

export function ConfirmationCard({ pending, onDecide }: ConfirmationCardProps): React.JSX.Element {
  const [busy, setBusy] = useState<ConfirmationDecision | null>(null)
  const [failed, setFailed] = useState<string | null>(null)

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
        setFailed(error instanceof Error ? error.message : 'That didn’t go through.')
      } finally {
        setBusy(null)
      }
    },
    [onDecide]
  )

  return (
    <section
      aria-label="Action needs your approval"
      style={{
        border: '1px solid var(--acc)',
        borderRadius: 8,
        padding: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 8
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <strong>SOL needs your approval</strong>
        <Mono style={{ color: 'var(--mut)' }}>{pending.tool}</Mono>
      </div>

      <p style={{ margin: 0 }}>{pending.summary}</p>

      {pending.preview.length > 0 ? (
        <ul aria-label="Proposed changes" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {pending.preview.map((row, index) => (
            <DiffRow key={`${row.label}-${index}`} row={row} />
          ))}
        </ul>
      ) : (
        <Mono style={{ color: 'var(--mut)' }}>
          This tool could not describe its change — review the action above before approving.
        </Mono>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <button type="button" onClick={() => void decide('approve')} disabled={busy !== null}>
          {busy === 'approve' ? 'Applying…' : 'Approve'}
        </button>
        <button type="button" onClick={() => void decide('reject')} disabled={busy !== null}>
          Reject
        </button>
      </div>

      {failed !== null && (
        <Mono style={{ ...VERBATIM, color: 'var(--acc)' }}>
          {failed} The action is still waiting for you.
        </Mono>
      )}
    </section>
  )
}
