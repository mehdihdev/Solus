// SOLUSDEV-319: the Ember Pill plan card (docs/wireflows/sol-window.md
// "SOLUSDEV-319 Ember Pill"). A PRESENTATION of the existing parked approvals,
// never a new approval path:
// - every step shows its summary and its verbatim before → after rows, so what
//   is approved is what is shown (CLAUDE.md §7);
// - Run approves the steps ONE AT A TIME through the same decision call the
//   single card uses, each awaited, so each keeps its server-side staleness
//   re-check (the reason SOLUSDEV-168 refused batch approval);
// - the first failure stops the run; a refused step is never sent again.
// Command cards (SOLUSDEV-317) never come here — they keep their own card.
import { useRef, useState } from 'react'
import { Mono } from '../../components/ui/Mono'
import type { ConfirmationRow, PendingConfirmation } from '../../lib/api/solStream'
import type { ConfirmationDecision } from './ConfirmationCard'
import './PlanCard.css'

export interface PlanCardProps {
  readonly steps: readonly PendingConfirmation[]
  readonly onDecide: (confirmationId: string, decision: ConfirmationDecision) => Promise<void>
  /** After the steps are declined: switch to Guide and ask SOL to walk the user through it. */
  readonly onShowMe: () => void
}

interface Failure {
  message: string
  terminal: boolean
}

/** Same split as the single card: a server refusal is final, a transport failure is not. */
function toFailure(error: unknown): Failure {
  return {
    message: error instanceof Error ? error.message : 'That didn’t go through.',
    terminal: error instanceof Error && error.name === 'ConfirmationRefused'
  }
}

const plural = (n: number): string => `${n} ${n === 1 ? 'step' : 'steps'}`

function usePlanRun(onDecide: PlanCardProps['onDecide']): {
  progress: { done: number; queue: readonly PendingConfirmation[] } | null
  failed: Failure | null
  refused: ReadonlySet<string>
  run: (queue: readonly PendingConfirmation[], decision: ConfirmationDecision) => Promise<boolean>
  stop: () => void
} {
  const [progress, setProgress] = useState<{
    done: number
    queue: readonly PendingConfirmation[]
  } | null>(null)
  const [failed, setFailed] = useState<Failure | null>(null)
  const [refused, setRefused] = useState<ReadonlySet<string>>(new Set())
  const busy = useRef(false)
  const stopped = useRef(false)

  /** Decide each step in order; false when a failure or Stop cut it short. */
  const run = async (
    queue: readonly PendingConfirmation[],
    decision: ConfirmationDecision
  ): Promise<boolean> => {
    if (busy.current || queue.length === 0) return false
    busy.current = true
    stopped.current = false
    setFailed(null)
    let finished = true
    for (const [index, step] of queue.entries()) {
      if (stopped.current) {
        finished = false
        break
      }
      if (decision === 'approve') setProgress({ done: index, queue })
      try {
        await onDecide(step.confirmationId, decision)
      } catch (error) {
        const failure = toFailure(error)
        setFailed(failure)
        if (failure.terminal) setRefused((ids) => new Set([...ids, step.confirmationId]))
        finished = false
        break
      }
    }
    setProgress(null)
    busy.current = false
    return finished
  }
  return { progress, failed, refused, run, stop: () => void (stopped.current = true) }
}

function Rows({ rows }: { rows: readonly ConfirmationRow[] }): React.JSX.Element {
  if (rows.length === 0) {
    return <div className="sol-plan-row">This step could not describe its change.</div>
  }
  return (
    <>
      {rows.map((row, index) => (
        <div className="sol-plan-row" key={`${row.label}-${index}`}>
          <span className="sol-plan-label">{row.label}</span>{' '}
          <span className="sol-plan-before">{row.before ?? '—'}</span>
          {' → '}
          <span className="sol-plan-after">{row.after ?? '—'}</span>
        </div>
      ))}
    </>
  )
}

function Running({
  done,
  queue,
  onStop
}: {
  done: number
  queue: readonly PendingConfirmation[]
  onStop: () => void
}): React.JSX.Element {
  return (
    <div className="sol-plan-running">
      <div className="sol-plan-running-head">
        <Mono size={9.5} color="var(--acc)">
          {`APPLYING · STEP ${done + 1} OF ${queue.length}`}
        </Mono>
        <span className="sol-plan-current">{queue[done]?.summary}</span>
        <button type="button" className="sol-plan-stop" onClick={onStop}>
          Stop
        </button>
      </div>
      <div className="sol-plan-progress" aria-hidden>
        {queue.map((step, index) => (
          <span
            key={step.confirmationId}
            data-state={index < done ? 'done' : index === done ? 'active' : 'todo'}
          />
        ))}
      </div>
    </div>
  )
}

export function PlanCard({ steps, onDecide, onShowMe }: PlanCardProps): React.JSX.Element {
  const plan = usePlanRun(onDecide)
  const runnable = steps.filter((s) => !plan.refused.has(s.confirmationId))
  const idle = plan.progress === null
  return (
    <section className="sol-plan" aria-label="Plan needs your approval">
      <Mono size={9.5} color="var(--mut)">{`PLAN · ${plural(steps.length).toUpperCase()}`}</Mono>
      <ol className="sol-plan-steps" aria-label="Plan steps">
        {steps.map((step) => (
          <li key={step.confirmationId} className="sol-plan-step">
            <span className="sol-plan-summary">{step.summary}</span>
            <Rows rows={step.preview} />
          </li>
        ))}
      </ol>
      {plan.failed && (
        <div role="alert" className="sol-plan-failed" data-terminal={plan.failed.terminal}>
          {plan.failed.message}{' '}
          {plan.failed.terminal
            ? 'That step can’t be retried — ask SOL again if you still want it.'
            : 'The steps are still waiting for you.'}
        </div>
      )}
      {plan.progress ? (
        <Running done={plan.progress.done} queue={plan.progress.queue} onStop={plan.stop} />
      ) : (
        <div className="sol-plan-actions">
          {runnable.length > 0 && (
            <button
              type="button"
              className="sol-plan-run"
              onClick={() => void plan.run(runnable, 'approve')}
            >
              {`Run ${plural(runnable.length)}`}
            </button>
          )}
          <button
            type="button"
            className="sol-plan-secondary"
            disabled={!idle}
            onClick={() =>
              void plan.run(runnable, 'reject').then((ok) => {
                if (ok) onShowMe()
              })
            }
          >
            Show me how instead
          </button>
          <button
            type="button"
            className="sol-plan-bare"
            disabled={!idle}
            onClick={() => void plan.run(runnable, 'reject')}
          >
            Reject
          </button>
        </div>
      )}
    </section>
  )
}
