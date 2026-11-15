// SOLUSDEV-326: what SOL is doing while it works — its thought summary and each tool step, in
// order — above the reply (docs/wireflows/sol-page.md). Open while the turn runs (the person can
// fold it any time); when the turn ends it folds into "Thought for 12s · 3 steps". Guide keeps it
// open after the answer, where the reasoning is part of the teaching; Expert folds it until asked
// (ADR-016: the mode is universal). Opening and closing animate (ThinkingBlock.css).
//
// The thought is model text the server masked and bounded (agent/thinking.py) and solStream bounded
// again. Provider summaries are written in markdown (`**Checking the bus**`), so it renders through
// SolMarkdown, the same renderer as the answer: React elements only — raw HTML skipped, links
// inert, images dropped (Markdown.test.tsx). A step shows
// the server's redacted args (TraceArgs) and the same `tool → outcome` words the backend persists.
import { Fragment, useEffect, useState } from 'react'
import { useSettingsStore } from '../../store/settingsStore'
import type { ChatItem, TraceEntry } from './solChatStore'
import { SolMarkdown } from './Markdown'
import { humanizeTool, thoughtSummary, type ThoughtSegment } from './thinking'
import { TraceArgs } from './TraceArgs'
import './ThinkingBlock.css'

type StepState = 'running' | 'ok' | 'error'

const stepState = (step: TraceEntry): StepState =>
  step.ok === null ? 'running' : step.ok ? 'ok' : 'error'

const STEP_MARK: Record<StepState, string> = { running: '●', ok: '✓', error: '✕' }

function Step({ step }: { step: TraceEntry }): React.JSX.Element {
  const state = stepState(step)
  const outcome =
    state === 'running' ? 'running…' : state === 'ok' ? 'ok' : (step.errorCode ?? 'error')
  return (
    <div data-step={state} className="sol-thinking-step sol-thinking-entry">
      <span aria-hidden className="sol-thinking-mark">
        {STEP_MARK[state]}
      </span>
      <span className="sol-thinking-name">{humanizeTool(step.tool)}</span>
      <div className="sol-thinking-detail">
        {step.tool} → {outcome}
        <TraceArgs args={step.args} />
      </div>
    </div>
  )
}

function Thoughts({ segments }: { segments: readonly ThoughtSegment[] }): React.JSX.Element {
  return (
    <>
      {segments.map((segment, i) => (
        <div key={i} className="sol-thinking-thought sol-thinking-entry">
          <SolMarkdown content={segment.text} />
        </div>
      ))}
    </>
  )
}

/** The thought and the steps interleaved: each segment sits after the steps that preceded it. */
function Body({ item }: { item: ChatItem }): React.JSX.Element {
  const segments = item.thinking?.segments ?? []
  const at = (steps: number): ThoughtSegment[] => segments.filter((s) => s.afterSteps === steps)
  const trailing = segments.filter((s) => s.afterSteps > item.trace.length)
  return (
    <div data-testid="thinking-body" className="sol-thinking-body">
      {item.trace.map((step, i) => (
        <Fragment key={step.callId}>
          <Thoughts segments={at(i)} />
          <Step step={step} />
        </Fragment>
      ))}
      <Thoughts segments={[...at(item.trace.length), ...trailing]} />
    </div>
  )
}

/** Whether the panel is mounted and whether it shows. It mounts on first open and stays mounted,
 *  and `shown` follows `open` one frame later, so both the open and the close transition run. A
 *  block that starts open (a live turn) shows at once, with no entry animation. */
function usePanel(open: boolean): { mounted: boolean; shown: boolean } {
  const [mounted, setMounted] = useState(open)
  const [shown, setShown] = useState(open)
  useEffect(() => {
    if (open) setMounted(true)
    const frame = requestAnimationFrame(() => setShown(open))
    return () => cancelAnimationFrame(frame)
  }, [open])
  return { mounted: mounted || open, shown }
}

export function ThinkingBlock({ item }: { item: ChatItem }): React.JSX.Element | null {
  const guide = useSettingsStore((state) => state.solMode === 'Guide')
  const [chosen, setChosen] = useState<boolean | null>(null)
  // Live for the whole turn: text SOL writes before a tool call is not the end of its work.
  const live = item.pending
  const open = chosen ?? (live || guide)
  const panel = usePanel(open)
  if (!item.thinking && item.trace.length === 0) return null
  return (
    <div data-testid="thinking-block" className="sol-thinking">
      <button
        type="button"
        className="sol-thinking-toggle"
        aria-expanded={open}
        onClick={() => setChosen(!open)}
      >
        {live ? (
          <span className="sol-thinking-live">Thinking…</span>
        ) : (
          thoughtSummary(item.thinking, item.trace.length)
        )}
        <svg
          aria-hidden
          className="sol-thinking-chevron"
          data-open={open}
          width="8"
          height="8"
          viewBox="0 0 8 8"
        >
          <path
            d="M2.5 1.5 5.5 4 2.5 6.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      {panel.mounted && (
        <div
          data-testid="thinking-panel"
          className="sol-thinking-panel"
          data-open={panel.shown && open}
          aria-hidden={!open}
          inert={!open}
        >
          <div className="sol-thinking-clip">
            <Body item={item} />
          </div>
        </div>
      )}
    </div>
  )
}
