// The shared-view surfaces around the robot panels (wireflow live-bench-view.md "Layout",
// §1.2, §8): above them the pinned strip, a write-failure line and the 6 s Undo toast;
// below them the Derived panel and "Hidden signals (n)". All read the BenchViewContext.
import { useEffect, useState } from 'react'
import type { BenchViewDerived, BenchViewDisplayEntry, BenchViewTarget } from '@solus/shared-types'
import type { BenchSignalSeries } from '../../../lib/api/resources'
import { SignalWidget } from '../SignalWidget'
import { useBenchViewContext, type BenchViewContextValue } from './BenchViewContext'
import type { DerivedSeries } from './derivedSignals'
import { ConfirmDelete, DerivedCard, DerivedPanel } from './DerivedPanel'
import { DerivedSignalEditor } from './DerivedSignalEditor'
import { useBenchViewStore, type BenchViewEdit } from './useBenchView'
import { useDerivedSeries } from './useDerivedSeries'
import { hiddenEntries, pinnedEntries, reorderOps } from './viewLayout'

export const UNDO_WINDOW_MS = 6_000
const NO_DERIVED: readonly BenchViewDerived[] = []

function useLiveDerived(context: BenchViewContextValue | null): DerivedSeries[] {
  return useDerivedSeries(context?.view?.derived ?? NO_DERIVED, context?.devices ?? {})
}

function signalSeries(
  context: BenchViewContextValue,
  deviceId: string,
  signal: string
): BenchSignalSeries {
  const device = Object.hasOwn(context.devices, deviceId) ? context.devices[deviceId] : undefined
  return device?.signals.find((series) => series.signal === signal) ?? { signal, points: [] }
}

export function BenchViewTop(): React.JSX.Element | null {
  const context = useBenchViewContext()
  const series = useLiveDerived(context)
  if (!context) return null
  return (
    <>
      <PinnedStrip context={context} series={series} />
      <WriteNotice projectId={context.projectId} />
      {context.canEdit && <UndoToast projectId={context.projectId} />}
    </>
  )
}

export function BenchViewBottom(): React.JSX.Element | null {
  const context = useBenchViewContext()
  const series = useLiveDerived(context)
  if (!context) return null
  return (
    <>
      <DerivedPanel series={series} />
      <HiddenSignals context={context} />
    </>
  )
}

function PinnedStrip({
  context,
  series
}: {
  context: BenchViewContextValue
  series: readonly DerivedSeries[]
}): React.JSX.Element | null {
  const [sheet, setSheet] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<BenchViewDerived | null>(null)
  const pinned = pinnedEntries(context.view)
  if (pinned.length === 0) return null
  const move = (from: number, to: number): void => {
    const ops = reorderOps(
      pinned.map((entry) => [{ target: entry.target, order: entry.order }]),
      from,
      to
    )
    if (ops.length) void useBenchViewStore.getState().setDisplay(context.projectId, ops)
  }
  return (
    <section aria-label="Pinned" className="bench-secondary">
      <div className="bench-section-heading">
        <span>PINNED</span>
      </div>
      <div className="bench-signal-grid">
        {pinned.map((entry, index) => (
          <PinnedCard
            key={JSON.stringify(entry.target)}
            context={context}
            entry={entry}
            series={series}
            onMove={context.canEdit ? (delta) => move(index, index + delta) : undefined}
            onEdit={setSheet}
            onDelete={setDeleting}
          />
        ))}
      </div>
      {deleting && <ConfirmDelete derived={deleting} onDone={() => setDeleting(null)} />}
      {sheet && context.canEdit && (
        <DerivedSignalEditor
          projectId={context.projectId}
          devices={context.devices}
          derivedId={sheet}
          onClose={() => setSheet(null)}
        />
      )}
    </section>
  )
}

function PinnedCard({
  context,
  entry,
  series,
  onMove,
  onEdit,
  onDelete
}: {
  context: BenchViewContextValue
  entry: BenchViewDisplayEntry
  series: readonly DerivedSeries[]
  onMove?: (delta: -1 | 1) => void
  onEdit: (id: string) => void
  onDelete: (derived: BenchViewDerived) => void
}): React.JSX.Element | null {
  const { target } = entry
  if (target.kind === 'signal')
    return (
      <SignalWidget
        userId={null}
        projectId={context.projectId}
        deviceId={target.device_id}
        series={signalSeries(context, target.device_id, target.signal)}
        onMove={onMove}
      />
    )
  const derived = context.view?.derived.find((row) => row.id === target.id)
  if (!derived) return null
  return (
    <DerivedCard
      derived={derived}
      series={series.find((row) => row.id === derived.id)}
      onEdit={onEdit}
      onDelete={onDelete}
      onMove={onMove}
    />
  )
}

function WriteNotice({ projectId }: { projectId: string }): React.JSX.Element | null {
  const notice = useBenchViewStore((state) => state.projects[projectId]?.notice ?? null)
  if (!notice) return null
  return (
    <p role="alert" className="bench-device-chips">
      {notice}{' '}
      <button
        type="button"
        className="bench-text-button"
        onClick={() => useBenchViewStore.getState().dismissNotice(projectId)}
      >
        Dismiss
      </button>
    </p>
  )
}

function UndoToast({ projectId }: { projectId: string }): React.JSX.Element | null {
  const lastEdit = useBenchViewStore((state) => state.projects[projectId]?.lastEdit ?? null)
  const [expired, setExpired] = useState<number | null>(null)
  const [failed, setFailed] = useState<number | null>(null)
  useEffect(() => {
    if (!lastEdit) return
    const timer = setTimeout(
      () => setExpired(lastEdit.at),
      Math.max(0, lastEdit.at + UNDO_WINDOW_MS - Date.now())
    )
    return () => clearTimeout(timer)
  }, [lastEdit])
  if (!lastEdit || expired === lastEdit.at) return null
  if (failed === lastEdit.at) return <p role="status">View changed since — Undo unavailable</p>
  const edit: BenchViewEdit = { version: lastEdit.version, inverseOps: lastEdit.inverseOps }
  async function run(): Promise<void> {
    const outcome = await useBenchViewStore.getState().undo(projectId, edit)
    if (!outcome.ok) setFailed(lastEdit!.at)
  }
  return (
    <p role="status" className="bench-device-chips">
      Bench view updated{' '}
      <button type="button" className="bench-text-button" onClick={() => void run()}>
        Undo
      </button>
    </p>
  )
}

function targetLabel(context: BenchViewContextValue, target: BenchViewTarget): string {
  if (target.kind === 'signal') return `${target.device_id} · ${target.signal}`
  return context.view?.derived.find((row) => row.id === target.id)?.name ?? 'Derived signal'
}

function HiddenSignals({ context }: { context: BenchViewContextValue }): React.JSX.Element | null {
  const [open, setOpen] = useState(false)
  const hidden = hiddenEntries(context.view)
  if (hidden.length === 0) return null
  const show = (target: BenchViewTarget): void =>
    void useBenchViewStore
      .getState()
      .setDisplay(context.projectId, [{ kind: 'set_display', target, patch: { hidden: null } }])
  return (
    <section className="bench-secondary">
      <button
        type="button"
        className="bench-text-button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {`Hidden signals (${hidden.length})`}
      </button>
      {open && (
        <ul aria-label="Hidden signals">
          {hidden.map((entry) => (
            <li key={JSON.stringify(entry.target)}>
              {targetLabel(context, entry.target)}
              {context.canEdit && (
                <button
                  type="button"
                  className="bench-text-button"
                  onClick={() => show(entry.target)}
                >
                  Show
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
