// SOLUSDEV-326: what SOL is doing while it works — its thought summary and each tool step, in
// order — above the reply (docs/wireflows/sol-page.md). Open while SOL thinks; once the answer
// starts it folds into "Thought for 12s · 3 steps". Guide keeps it open after the answer, where the
// reasoning is part of the teaching; Expert folds it until asked (ADR-016: the mode is universal).
//
// The thought is model text the server masked and bounded (agent/thinking.py) and solStream bounded
// again, so it renders as text nodes only — never markdown, never HTML, never a link. A step shows
// the server's redacted args (TraceArgs) and the same `tool → outcome` words the backend persists.
import { Fragment, useState } from 'react'
import { useSettingsStore } from '../../store/settingsStore'
import type { ChatItem, TraceEntry } from './solChatStore'
import { humanizeTool, thoughtSummary, type ThoughtSegment } from './thinking'
import { TraceArgs } from './TraceArgs'
import './ThinkingBlock.css'

const MUTED: React.CSSProperties = { fontSize: 11, color: 'var(--mut)' }

const TOGGLE: React.CSSProperties = {
  ...MUTED,
  display: 'inline-flex',
  alignItems: 'center',
  gap: 5,
  padding: 0,
  border: 'none',
  background: 'none',
  cursor: 'pointer',
  userSelect: 'none'
}

const BODY: React.CSSProperties = {
  margin: '4px 0 6px',
  padding: '2px 0 2px 10px',
  borderLeft: '2px solid var(--bd)',
  fontSize: 12,
  lineHeight: 1.5,
  color: 'var(--mut)'
}

const THOUGHT: React.CSSProperties = { margin: '2px 0 6px', whiteSpace: 'pre-wrap' }

type StepState = 'running' | 'ok' | 'error'

const stepState = (step: TraceEntry): StepState =>
  step.ok === null ? 'running' : step.ok ? 'ok' : 'error'

const STEP_MARK: Record<StepState, string> = { running: '●', ok: '✓', error: '✕' }

function Step({ step }: { step: TraceEntry }): React.JSX.Element {
  const state = stepState(step)
  const outcome =
    state === 'running' ? 'running…' : state === 'ok' ? 'ok' : (step.errorCode ?? 'error')
  return (
    <div data-step={state} style={{ padding: '2px 0' }}>
      <span
        aria-hidden
        className={state === 'running' ? 'sol-thinking-pulse' : undefined}
        style={{ color: state === 'error' ? 'var(--err)' : 'var(--acc)', marginRight: 6 }}
      >
        {STEP_MARK[state]}
      </span>
      <span style={{ color: 'var(--tx)' }}>{humanizeTool(step.tool)}</span>
      <div style={{ ...MUTED, fontFamily: 'var(--font-mono)', paddingLeft: 16 }}>
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
        <p key={i} style={THOUGHT}>
          {segment.text}
        </p>
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
    <div data-testid="thinking-body" style={BODY}>
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

export function ThinkingBlock({ item }: { item: ChatItem }): React.JSX.Element | null {
  const guide = useSettingsStore((state) => state.solMode === 'Guide')
  const [chosen, setChosen] = useState<boolean | null>(null)
  if (!item.thinking && item.trace.length === 0) return null
  const live = item.pending && !item.content
  const open = live || (chosen ?? guide)
  return (
    <div data-testid="thinking-block" style={{ margin: '2px 0 4px' }}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setChosen(!open)}
        disabled={live}
        style={TOGGLE}
      >
        {live ? (
          <span className="sol-thinking-live">Thinking…</span>
        ) : (
          thoughtSummary(item.thinking, item.trace.length)
        )}
        {!live && (
          <span aria-hidden style={{ fontSize: 9 }}>
            {open ? '▾' : '▸'}
          </span>
        )}
      </button>
      {open && <Body item={item} />}
    </div>
  )
}
