// The Derived panel (wireflow live-bench-view.md "Layout", §2): every derived signal not
// hidden or pinned, rendered as a signal card from its live DerivedSignalStream series;
// "+ Derived signal" and ⋯ → Edit open the side sheet; ⋯ → Delete asks first.
import { useState } from 'react'
import type { BenchViewDerived } from '@solus/shared-types'
import { SignalWidget } from '../SignalWidget'
import { useBenchViewContext } from './BenchViewContext'
import type { DerivedSeries } from './derivedSignals'
import { derivedCardSeries } from './derivedDraft'
import { DerivedSignalEditor } from './DerivedSignalEditor'
import { useBenchViewStore } from './useBenchView'
import { displayFor } from './viewOps'

const CONFLICT_TEXT = 'A teammate changed the bench view. Reload to see it, then save again.'

export interface DerivedCardProps {
  derived: BenchViewDerived
  series: DerivedSeries | undefined
  onEdit: (id: string) => void
  onDelete: (derived: BenchViewDerived) => void
  onMove?: (delta: -1 | 1) => void
}

export function DerivedCard({
  derived,
  series,
  onEdit,
  onDelete,
  onMove
}: DerivedCardProps): React.JSX.Element {
  const context = useBenchViewContext()
  return (
    <SignalWidget
      userId={null}
      projectId={context?.projectId ?? ''}
      deviceId={`derived:${derived.id}`}
      target={{ kind: 'derived', id: derived.id }}
      series={derivedCardSeries(series, derived.name)}
      onMove={onMove}
      derived={{
        expression: derived.expression,
        onEdit: () => onEdit(derived.id),
        onDelete: () => onDelete(derived)
      }}
    />
  )
}

type Sheet = { id: string | null } | null

export function DerivedPanel({
  series
}: {
  series: readonly DerivedSeries[]
}): React.JSX.Element | null {
  const context = useBenchViewContext()
  const [sheet, setSheet] = useState<Sheet>(null)
  const [deleting, setDeleting] = useState<BenchViewDerived | null>(null)
  if (!context) return null
  const shown = (context.view?.derived ?? []).filter((derived) => {
    const settings = displayFor(context.view, { kind: 'derived', id: derived.id })
    return !settings.hidden && !settings.pinned
  })
  return (
    <section aria-label="Derived" className="bench-secondary">
      <div className="bench-section-heading">
        <span>DERIVED</span>
      </div>
      <div className="bench-signal-grid">
        {shown.map((derived) => (
          <DerivedCard
            key={derived.id}
            derived={derived}
            series={series.find((row) => row.id === derived.id)}
            onEdit={(id) => setSheet({ id })}
            onDelete={setDeleting}
          />
        ))}
      </div>
      {context.canEdit && (
        <button type="button" className="bench-text-button" onClick={() => setSheet({ id: null })}>
          + Derived signal
        </button>
      )}
      {deleting && <ConfirmDelete derived={deleting} onDone={() => setDeleting(null)} />}
      {sheet && context.canEdit && (
        <DerivedSignalEditor
          projectId={context.projectId}
          devices={context.devices}
          derivedId={sheet.id}
          onClose={() => setSheet(null)}
        />
      )}
    </section>
  )
}

export function ConfirmDelete({
  derived,
  onDone
}: {
  derived: BenchViewDerived
  onDone: () => void
}): React.JSX.Element | null {
  const context = useBenchViewContext()
  const [error, setError] = useState<string | null>(null)
  if (!context) return null
  async function remove(): Promise<void> {
    const outcome = await useBenchViewStore
      .getState()
      .saveDerived(context!.projectId, [{ kind: 'delete_derived', id: derived.id }])
    if (outcome.ok) return onDone()
    setError(
      outcome.failure.kind === 'conflict'
        ? CONFLICT_TEXT
        : outcome.failure.kind === 'refused'
          ? outcome.failure.message
          : 'The derived signal could not be deleted.'
    )
  }
  return (
    <div role="alertdialog" aria-label={`Delete ${derived.name}`}>
      <p>Delete {derived.name}? Charts that use it lose it.</p>
      {error && <p role="alert">{error}</p>}
      <button type="button" className="bench-text-button" onClick={onDone}>
        Cancel
      </button>
      <button type="button" onClick={() => void remove()}>
        Delete
      </button>
    </div>
  )
}
