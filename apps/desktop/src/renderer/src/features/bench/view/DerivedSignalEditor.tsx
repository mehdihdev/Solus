// The derived-signal side sheet (wireflow live-bench-view.md §2, §3.2, §4.2). The renderer's
// parser gives inline errors as the user types (Save stays enabled; the server is the
// authority), the preview evaluates the draft on the streams already in memory, and a save
// is one `upsert_derived` that never auto-retries. Every string is rendered as escaped text.
import { useRef, useState } from 'react'
import { BENCH_VIEW_LIMITS, type BenchViewDerived, type UpsertDerivedOp } from '@solus/shared-types'
import type { BenchDeviceRecent } from '../../../lib/api/resources'
import { chartSegments } from '../../../widgets/livebench/telemetry'
import { formatValue } from '../signalUnits'
import { previewDerivedSignal } from './derivedSignals'
import {
  insertAt,
  missingRefs,
  referenceText,
  splitAtError,
  streamingSignals,
  type ErrorSpan
} from './derivedDraft'
import { MAX_NODES, MAX_REFS, tryParseExpression, type ParsedExpression } from './expression'
import { useBenchViewStore, type BenchViewWriteOutcome } from './useBenchView'

type Devices = Readonly<Record<string, BenchDeviceRecent>>

export interface DerivedSignalEditorProps {
  projectId: string
  devices: Devices
  /** null creates a new derived signal. */
  derivedId: string | null
  onClose: () => void
}

interface Draft {
  name: string
  unit: string
  expression: string
}

type Feedback =
  | { kind: 'expression'; span: ErrorSpan }
  | { kind: 'name'; message: string }
  | { kind: 'conflict' }
  | { kind: 'other'; message: string }

const CONFLICT_TEXT = 'A teammate changed the bench view. Reload to see it, then save again.'
const FUNCTIONS = ['abs', 'min', 'max', 'clamp', 'scale', 'ma', 'lowpass', 'deriv', 'integ']
const draftOf = (derived: BenchViewDerived | undefined): Draft => ({
  name: derived?.name ?? '',
  unit: derived?.unit ?? '',
  expression: derived?.expression ?? ''
})
const keyOf = (derived: BenchViewDerived | undefined): string => derived?.updated_at ?? 'deleted'

function feedbackFor(outcome: Extract<BenchViewWriteOutcome, { ok: false }>): Feedback {
  const { failure } = outcome
  if (failure.kind === 'conflict') return { kind: 'conflict' }
  if (failure.kind === 'expression') {
    const detail = failure.details.find((row) => row.op_index === 0) ?? failure.details[0]
    if (detail) return { kind: 'expression', span: detail }
    return { kind: 'other', message: 'The expression was refused.' }
  }
  if (failure.kind === 'refused' && failure.code === 'duplicate_name')
    return { kind: 'name', message: failure.message }
  if (failure.kind === 'refused') return { kind: 'other', message: failure.message }
  return { kind: 'other', message: 'The derived signal could not be saved. Check your connection.' }
}

interface EditorState {
  draft: Draft
  setDraft: React.Dispatch<React.SetStateAction<Draft>>
  changed: boolean
  reload: () => void
  keepEditing: () => void
  baseVersion: () => number | undefined
}

/** The signal under edit, the draft, and whether a teammate changed it since we opened it. */
function useEditorState(projectId: string, derivedId: string | null): EditorState {
  const view = useBenchViewStore((state) => state.projects[projectId]?.view ?? null)
  const current = derivedId ? view?.derived.find((row) => row.id === derivedId) : undefined
  const [draft, setDraft] = useState<Draft>(() => draftOf(current))
  const [base, setBase] = useState(() => ({ key: keyOf(current), version: view?.version ?? 0 }))
  const changed = derivedId !== null && keyOf(current) !== base.key
  return {
    draft,
    setDraft,
    changed,
    reload: () => {
      setDraft(draftOf(current))
      setBase({ key: keyOf(current), version: view?.version ?? 0 })
    },
    keepEditing: () => setBase((previous) => ({ ...previous, key: keyOf(current) })),
    /** Unrelated team edits do not invalidate the draft; a changed signal keeps its stale base. */
    baseVersion: (): number | undefined =>
      derivedId === null
        ? undefined
        : changed || base.key !== keyOf(current)
          ? base.version
          : view?.version
  }
}

export function DerivedSignalEditor({
  projectId,
  devices,
  derivedId,
  onClose
}: DerivedSignalEditorProps): React.JSX.Element {
  const state = useEditorState(projectId, derivedId)
  const { draft, setDraft } = state
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [saving, setSaving] = useState(false)
  const edit = (change: Partial<Draft>): void => {
    setDraft((previous) => ({ ...previous, ...change }))
    if (feedback?.kind !== 'conflict') setFeedback(null)
  }
  async function save(): Promise<void> {
    const op: UpsertDerivedOp = {
      kind: 'upsert_derived',
      ...(derivedId ? { id: derivedId } : {}),
      name: draft.name.trim(),
      expression: draft.expression,
      unit: draft.unit.trim() || null
    }
    if (!op.name) return setFeedback({ kind: 'name', message: 'Name is required.' })
    const base = state.baseVersion()
    const store = useBenchViewStore.getState()
    setSaving(true)
    const outcome = await (base === undefined
      ? store.saveDerived(projectId, [op])
      : store.saveDerived(projectId, [op], base))
    setSaving(false)
    if (outcome.ok) onClose()
    else setFeedback(feedbackFor(outcome))
  }
  return (
    <aside
      role="dialog"
      aria-label="Derived signal"
      className="bench-signal-card"
      style={{ display: 'grid', gap: 8 }}
    >
      <h2 style={{ margin: 0, fontSize: '1rem' }}>Derived signal</h2>
      {state.changed && <TeammateBanner onReload={state.reload} onKeep={state.keepEditing} />}
      <NameField
        draft={draft}
        edit={edit}
        error={feedback?.kind === 'name' ? feedback.message : null}
      />
      <label>
        Unit{' '}
        <input
          aria-label="Unit"
          maxLength={BENCH_VIEW_LIMITS.maxUnitChars}
          value={draft.unit}
          onChange={(e) => edit({ unit: e.target.value })}
        />
      </label>
      <ExpressionField
        expression={draft.expression}
        devices={devices}
        serverSpan={feedback?.kind === 'expression' ? feedback.span : null}
        onChange={(expression) => edit({ expression })}
      />
      <PreviewLine
        expression={draft.expression}
        unit={draft.unit.trim() || null}
        devices={devices}
      />
      <SaveFeedback
        feedback={feedback}
        onReload={() => void useBenchViewStore.getState().load(projectId)}
      />
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button type="button" className="bench-text-button" onClick={onClose}>
          Cancel
        </button>
        <button type="button" disabled={saving} onClick={() => void save()}>
          Save
        </button>
      </div>
    </aside>
  )
}

function TeammateBanner({
  onReload,
  onKeep
}: {
  onReload: () => void
  onKeep: () => void
}): React.JSX.Element {
  return (
    <div role="status">
      <span>Changed by a teammate</span>{' '}
      <button type="button" className="bench-text-button" onClick={onReload}>
        Reload
      </button>{' '}
      <button type="button" className="bench-text-button" onClick={onKeep}>
        Keep editing
      </button>
    </div>
  )
}

function NameField({
  draft,
  edit,
  error
}: {
  draft: Draft
  edit: (change: Partial<Draft>) => void
  error: string | null
}): React.JSX.Element {
  return (
    <label>
      Name{' '}
      <input
        aria-label="Name"
        aria-invalid={error ? true : undefined}
        maxLength={BENCH_VIEW_LIMITS.maxNameChars}
        value={draft.name}
        onChange={(event) => edit({ name: event.target.value })}
      />
      {error && <span style={{ color: 'var(--warning, #d97706)' }}> {error}</span>}
    </label>
  )
}

function SaveFeedback({
  feedback,
  onReload
}: {
  feedback: Feedback | null
  onReload: () => void
}): React.JSX.Element | null {
  if (feedback?.kind === 'conflict')
    return (
      <p role="status">
        {CONFLICT_TEXT}{' '}
        <button type="button" className="bench-text-button" onClick={onReload}>
          Reload
        </button>
      </p>
    )
  if (feedback?.kind === 'other') return <p role="alert">{feedback.message}</p>
  return null
}

function ExpressionField({
  expression,
  devices,
  serverSpan,
  onChange
}: {
  expression: string
  devices: Devices
  serverSpan: ErrorSpan | null
  onChange: (expression: string) => void
}): React.JSX.Element {
  const area = useRef<HTMLTextAreaElement>(null)
  const parsed = expression.trim() ? tryParseExpression(expression) : null
  const local = parsed && !parsed.ok ? parsed.error : null
  const span: ErrorSpan | null = serverSpan ?? local
  const insert = (text: string): void => {
    const next = insertAt(expression, area.current?.selectionStart ?? null, text)
    onChange(next.text)
  }
  return (
    <div style={{ display: 'grid', gap: 4 }}>
      <label htmlFor="derived-expression">Expression</label>
      <textarea
        id="derived-expression"
        ref={area}
        aria-label="Expression"
        rows={3}
        spellCheck={false}
        value={expression}
        onChange={(event) => onChange(event.target.value)}
        style={{ fontFamily: 'var(--font-mono, monospace)' }}
      />
      {span && <ErrorMirror expression={expression} span={span} />}
      {parsed?.ok && missingRefs(parsed.parsed.refs, devices).length > 0 && (
        <p role="status">⚠ No data yet for this signal (it may not be streaming)</p>
      )}
      <InsertBar
        counts={parsed?.ok ? countsText(parsed.parsed) : null}
        devices={devices}
        onInsert={insert}
      />
    </div>
  )
}

const countsText = (parsed: ParsedExpression): string =>
  `${parsed.nodeCount} / ${MAX_NODES} nodes · ${parsed.refs.length} / ${MAX_REFS} signals`

function ErrorMirror({
  expression,
  span
}: {
  expression: string
  span: ErrorSpan
}): React.JSX.Element {
  const split = splitAtError(expression, span)
  return (
    <>
      <pre
        aria-hidden="true"
        style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono, monospace)' }}
      >
        {split.before}
        <mark
          data-testid="expression-error-span"
          style={{
            textDecoration: 'underline wavy var(--warning, #d97706)',
            background: 'transparent',
            color: 'inherit'
          }}
        >
          {split.marked}
        </mark>
        {split.after}
      </pre>
      <p role="alert">{span.message}</p>
    </>
  )
}

function InsertBar({
  counts,
  devices,
  onInsert
}: {
  counts: string | null
  devices: Devices
  onInsert: (text: string) => void
}): React.JSX.Element {
  const signals = streamingSignals(devices)
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      {counts && <span>{counts}</span>}
      <select
        aria-label="Insert signal"
        value=""
        onChange={(event) => {
          const [deviceId, signal] = JSON.parse(event.target.value) as [string, string]
          onInsert(referenceText({ deviceId, signal }))
        }}
      >
        <option value="">Insert signal ▾</option>
        {signals.map((ref) => (
          <option
            key={`${ref.deviceId}\n${ref.signal}`}
            value={JSON.stringify([ref.deviceId, ref.signal])}
          >
            {ref.deviceId} · {ref.signal}
          </option>
        ))}
      </select>
      <select
        aria-label="Insert function"
        value=""
        onChange={(event) => onInsert(`${event.target.value}(`)}
      >
        <option value="">Insert function ▾</option>
        {FUNCTIONS.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
    </div>
  )
}

function PreviewLine({
  expression,
  unit,
  devices
}: {
  expression: string
  unit: string | null
  devices: Devices
}): React.JSX.Element {
  const preview = expression.trim() ? previewDerivedSignal(expression, devices) : null
  const points = (preview?.points ?? []).filter((point) => Number.isFinite(point.value))
  const latest = points.at(-1)
  const segments = chartSegments(points, 120, 24)
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      <span>Preview</span>
      <svg
        viewBox="0 0 120 24"
        role="img"
        aria-label="Preview chart"
        style={{ width: '7.5rem', height: '1.5rem', color: 'var(--bench-accent, var(--acc))' }}
      >
        {segments.map((segment, index) => (
          <polyline
            key={`${index}:${segment}`}
            points={segment}
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          />
        ))}
      </svg>
      <span aria-label="Preview value">
        {latest ? `${formatValue(latest.value, unit)}${unit ? ` ${unit}` : ''}` : '—'}
      </span>
    </div>
  )
}
