// SOLUSDEV-319 — the signal panel arranged by the shared view (wireflow live-bench-view.md
// "Layout", §1, §8): hidden and pinned cards leave the panel, order sorts, plot groups overlay.
import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EMPTY_BENCH_VIEW, type BenchView, type SignalTarget } from '@solus/shared-types'
import { BenchViewContext } from './BenchViewContext'
import { resetBenchViewStore, useBenchViewStore } from './useBenchView'
import { applyDisplayOps } from './viewOps'
import { ViewSignalGrid, type ViewSignalRow } from './ViewSignalGrid'

const DEVICE = 'usb:1/3'
const t = (signal: string): SignalTarget => ({ kind: 'signal', device_id: DEVICE, signal })
const row = (signal: string): ViewSignalRow => ({
  deviceId: DEVICE,
  key: JSON.stringify([DEVICE, signal]),
  stale: false,
  series: {
    signal,
    points: [
      { timestamp: '2026-09-14T12:00:00Z', value: 0, unit: 'rad' },
      { timestamp: '2026-09-14T12:00:01Z', value: 1, unit: 'rad' }
    ]
  }
})
const rows = ['a', 'b', 'c', 'd'].map(row)
const setDisplay = vi.fn(async () => ({ ok: true as const, version: 1, inverseOps: [] }))

function renderGrid(view: BenchView | null, canEdit = true): void {
  const grid = (
    <ViewSignalGrid rows={rows} userId="u" projectId="p1" events={[]} onScope={() => undefined} />
  )
  render(
    view === null ? (
      grid
    ) : (
      <BenchViewContext.Provider value={{ projectId: 'p1', view, canEdit, devices: {} }}>
        {grid}
      </BenchViewContext.Provider>
    )
  )
}
const cardNames = (): string[] =>
  screen
    .getAllByRole('region', { name: / signal$|plot group$/ })
    .map((card) => card.getAttribute('aria-label') ?? '')

beforeEach(() => {
  resetBenchViewStore()
  setDisplay.mockClear()
  useBenchViewStore.setState({ setDisplay })
})

describe('ViewSignalGrid', () => {
  it('keeps natural order outside the Live Bench view context', () => {
    renderGrid(null)
    expect(cardNames()).toEqual(['a signal', 'b signal', 'c signal', 'd signal'])
  })

  it('drops hidden and pinned cards and sorts by order', () => {
    renderGrid(
      applyDisplayOps(EMPTY_BENCH_VIEW, [
        { kind: 'set_display', target: t('a'), patch: { hidden: true } },
        { kind: 'set_display', target: t('b'), patch: { pinned: true } },
        { kind: 'set_display', target: t('d'), patch: { order: 0 } }
      ])
    )
    expect(cardNames()).toEqual(['d signal', 'c signal'])
  })

  it('overlays a plot group on one chart with a legend entry per member', () => {
    renderGrid(
      applyDisplayOps(EMPTY_BENCH_VIEW, [
        { kind: 'set_display', target: t('b'), patch: { plot_group: 'Shoulder' } },
        { kind: 'set_display', target: t('d'), patch: { plot_group: 'Shoulder' } }
      ])
    )
    expect(cardNames()).toEqual(['a signal', 'Shoulder plot group', 'c signal'])
    const group = screen.getByRole('region', { name: 'Shoulder plot group' })
    expect(
      within(group)
        .getAllByRole('listitem')
        .map((item) => item.textContent)
    ).toEqual(['b rad', 'd rad'])
    expect(within(group).getAllByTestId('group-line')).toHaveLength(2)
  })

  it('Move later sends one PATCH with the new orders', () => {
    renderGrid(EMPTY_BENCH_VIEW)
    fireEvent.click(screen.getByRole('button', { name: 'View options for a' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Move later' }))
    expect(setDisplay).toHaveBeenCalledWith('p1', [
      { kind: 'set_display', target: t('b'), patch: { order: 0 } },
      { kind: 'set_display', target: t('a'), patch: { order: 1 } }
    ])
  })

  it('drag-and-drop reorders for a member', () => {
    renderGrid(EMPTY_BENCH_VIEW)
    const items = screen.getAllByTestId('view-grid-item')
    fireEvent.dragStart(items[3])
    fireEvent.drop(items[0])
    expect(setDisplay).toHaveBeenCalledWith('p1', [
      { kind: 'set_display', target: t('d'), patch: { order: 0 } },
      { kind: 'set_display', target: t('a'), patch: { order: 1 } },
      { kind: 'set_display', target: t('b'), patch: { order: 2 } },
      { kind: 'set_display', target: t('c'), patch: { order: 3 } }
    ])
  })

  it('a viewer cannot drag', () => {
    renderGrid(EMPTY_BENCH_VIEW, false)
    for (const item of screen.getAllByTestId('view-grid-item'))
      expect(item).toHaveAttribute('draggable', 'false')
  })
})
