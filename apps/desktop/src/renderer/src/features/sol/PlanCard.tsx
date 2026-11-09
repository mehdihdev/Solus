// SOLUSDEV-319: the Ember Pill plan card (docs/wireflows/sol-window.md
// "SOLUSDEV-319 Ember Pill"). A PRESENTATION of the existing parked approvals,
// never a new approval path:
// - every step shows its tool, summary and verbatim before → after rows (the
//   single card's own DiffValue), so what is approved is what is shown (§7);
// - Run arms only once SOL has stopped answering AND every step has been in
//   view — a step that arrives later disarms it until it is seen (Phase 4 H1);
// - Run approves the steps ONE AT A TIME through the same decision call the
//   single card uses, each awaited, so each keeps its server-side staleness
//   re-check (the reason SOLUSDEV-168 refused batch approval);
// - the first failure stops the run; a refused step is marked and never sent
//   again; one plan runs at a time across the surface.
// Command cards (SOLUSDEV-317) never come here — they keep their own card.
import { useContext, useEffect, useRef, useState } from 'react'
import { Mono } from '../../components/ui/Mono'
import type { ConfirmationRow, PendingConfirmation } from '../../lib/api/solStream'
import { DiffValue, type ConfirmationDecision } from './ConfirmationCard'
import { PreviewObserverContext } from './previewInView'
import { useSolSessionStore } from './solSessionStore'
import { useSolWindowStore } from './solWindowStore'
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

interface Progress {
  done: number
  queue: readonly PendingConfirmation[]
}

function usePlanRun(onDecide: PlanCardProps['onDecide']): {
  progress: Progress | null
  running: boolean
  failed: Failure | null
  refused: ReadonlySet<string>
  run: (queue: readonly PendingConfirmation[], decision: ConfirmationDecision) => Promise<boolean>
  stop: () => void
} {
  const [progress, setProgress] = useState<Progress | null>(null)
  const [running, setRunning] = useState(false)
  const [failed, setFailed] = useState<Failure | null>(null)
  const [refused, setRefused] = useState<ReadonlySet<string>>(new Set())
  const stopped = useRef(false)
  const setPlanRunning = useSolWindowStore((s) => s.setPlanRunning)

  /** Decide each step in order; false when a failure or Stop cut it short. */
  const run = async (
    queue: readonly PendingConfirmation[],
    decision: ConfirmationDecision
  ): Promise<boolean> => {
    // The surface-wide lock, read live: a second plan (or a double click) waits.
    if (useSolWindowStore.getState().planRunning || queue.length === 0) return false
    setPlanRunning(true)
    setRunning(true)
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
    setRunning(false)
    setPlanRunning(false)
    return finished
  }
  return { progress, running, failed, refused, run, stop: () => void (stopped.current = true) }
}

/** Which steps have been on screen (sticky): Run arms only when all have. */
function useSeenSteps(): {
  seen: ReadonlySet<string>
  watch: (id: string) => (element: HTMLElement | null) => void
} {
  const observe = useContext(PreviewObserverContext)
  const [seen, setSeen] = useState<ReadonlySet<string>>(new Set())
  const stops = useRef(new Map<string, () => void>())
  useEffect(() => {
    const live = stops.current
    return () => live.forEach((stop) => stop())
  }, [])
  const watch =
    (id: string) =>
    (element: HTMLElement | null): void => {
      stops.current.get(id)?.()
      stops.current.delete(id)
      if (!element) return
      const markSeen = (inView: boolean): void => {
        if (inView) setSeen((ids) => (ids.has(id) ? ids : new Set([...ids, id])))
      }
      stops.current.set(id, observe(element, markSeen))
    }
  return { seen, watch }
}

function Rows({ rows }: { rows: readonly ConfirmationRow[] }): React.JSX.Element {
  if (rows.length === 0) {
    return <div className="sol-plan-row">This step could not describe its change.</div>
  }
  return (
    <>
      {rows.map((row, index) => (
        <div className="sol-plan-row" key={`${row.label}-${index}`}>
          <span className="sol-plan-label">{row.label}</span>
          <span className="sol-plan-before">
            <DiffValue value={row.before} />
          </span>
          <span aria-hidden>→</span>
          <span className="sol-plan-after">
            <DiffValue value={row.after} />
          </span>
        </div>
      ))}
    </>
  )
}

function Running({
  progress,
  onStop
}: {
  progress: Progress
  onStop: () => void
}): React.JSX.Element {
  const { done, queue } = progress
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

function Steps({
  steps,
  refused,
  watch
}: {
  steps: readonly PendingConfirmation[]
  refused: ReadonlySet<string>
  watch: (id: string) => (element: HTMLElement | null) => void
}): React.JSX.Element {
  return (
    <ol className="sol-plan-steps" aria-label="Plan steps">
      {steps.map((step) => {
        const isRefused = refused.has(step.confirmationId)
        return (
          <li
            key={step.confirmationId}
            ref={watch(step.confirmationId)}
            data-step={step.confirmationId}
            data-refused={isRefused}
            className="sol-plan-step"
          >
            <span className="sol-plan-summary">{step.summary}</span>
            <Mono size={9.5} color="var(--mut)" style={{ textTransform: 'none' }}>
              {step.tool}
            </Mono>
            {isRefused && <span className="sol-plan-refused">refused — won’t run</span>}
            <Rows rows={step.preview} />
          </li>
        )
      })}
    </ol>
  )
}

/** Why Run is not armed, in plain words — or null when it is. */
function holdReason(streaming: boolean, allSeen: boolean): string | null {
  if (streaming) return 'SOL is still answering — the plan may grow.'
  if (!allSeen) return 'Scroll through every step to enable Run.'
  return null
}

const planLabel = (runnable: number, refused: number): string =>
  `PLAN · ${plural(runnable).toUpperCase()}${refused ? ` · ${refused} REFUSED` : ''}`

function Actions({
  runnable,
  locked,
  hold,
  onRun,
  onShowMe,
  onReject
}: {
  runnable: number
  locked: boolean
  hold: string | null
  onRun: () => void
  onShowMe: () => void
  onReject: () => void
}): React.JSX.Element {
  return (
    <div className="sol-plan-actions">
      {runnable > 0 && (
        <button
          type="button"
          className="sol-plan-run"
          disabled={locked || hold !== null}
          onClick={onRun}
        >
          {`Run ${plural(runnable)}`}
        </button>
      )}
      <button type="button" className="sol-plan-secondary" disabled={locked} onClick={onShowMe}>
        Show me how instead
      </button>
      <button type="button" className="sol-plan-bare" disabled={locked} onClick={onReject}>
        Reject
      </button>
      {hold && !locked && <span className="sol-plan-hold">{hold}</span>}
    </div>
  )
}

function FailureLine({ failed }: { failed: Failure }): React.JSX.Element {
  return (
    <div role="alert" className="sol-plan-failed" data-terminal={failed.terminal}>
      {failed.message}{' '}
      {failed.terminal
        ? 'That step can’t be retried — ask SOL again if you still want it.'
        : 'The steps are still waiting for you.'}
    </div>
  )
}

export function PlanCard({ steps, onDecide, onShowMe }: PlanCardProps): React.JSX.Element {
  const plan = usePlanRun(onDecide)
  const { seen, watch } = useSeenSteps()
  const streaming = useSolSessionStore((s) => s.streaming)
  const otherRunning = useSolWindowStore((s) => s.planRunning) && !plan.running
  const runnable = steps.filter((s) => !plan.refused.has(s.confirmationId))
  const hold = holdReason(
    streaming,
    runnable.every((s) => seen.has(s.confirmationId))
  )
  return (
    <section className="sol-plan" aria-label="Plan needs your approval">
      <Mono size={9.5} color="var(--mut)">
        {planLabel(runnable.length, steps.length - runnable.length)}
      </Mono>
      <Steps steps={steps} refused={plan.refused} watch={watch} />
      {plan.failed && <FailureLine failed={plan.failed} />}
      {plan.progress ? (
        <Running progress={plan.progress} onStop={plan.stop} />
      ) : (
        <Actions
          runnable={runnable.length}
          locked={plan.running || otherRunning}
          hold={hold}
          onRun={() => void plan.run(runnable, 'approve')}
          onShowMe={() =>
            void plan.run(runnable, 'reject').then((ok) => {
              if (ok) onShowMe()
            })
          }
          onReject={() => void plan.run(runnable, 'reject')}
        />
      )}
    </section>
  )
}
