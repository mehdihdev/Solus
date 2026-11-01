import { describe, expect, it } from 'vitest'
import { EMPTY_BENCH_VIEW, type BenchView, type SignalTarget } from '@solus/shared-types'
import {
  arrangeSignals,
  hiddenEntries,
  pinnedEntries,
  reorderOps,
  type OrderedMember
} from './viewLayout'
import { applyDisplayOps } from './viewOps'

const t = (signal: string, device_id = 'usb:1/3'): SignalTarget => ({
  kind: 'signal',
  device_id,
  signal
})
const rows = ['a', 'b', 'c', 'd'].map((signal) => ({ deviceId: 'usb:1/3', signal }))
const withView = (...ops: Parameters<typeof applyDisplayOps>[1]): BenchView =>
  applyDisplayOps(EMPTY_BENCH_VIEW, ops)
const keys = (items: ReturnType<typeof arrangeSignals<(typeof rows)[number]>>['items']): string[] =>
  items.map((item) =>
    item.kind === 'card'
      ? item.row.signal
      : `[${item.group}:${item.rows.map((r) => r.signal).join(',')}]`
  )

describe('arrangeSignals', () => {
  it('keeps natural order with no view', () => {
    expect(keys(arrangeSignals(rows, null).items)).toEqual(['a', 'b', 'c', 'd'])
  })

  it('removes hidden and pinned cards from the panel', () => {
    const view = withView(
      { kind: 'set_display', target: t('b'), patch: { hidden: true } },
      { kind: 'set_display', target: t('c'), patch: { pinned: true } }
    )
    const arranged = arrangeSignals(rows, view)
    expect(keys(arranged.items)).toEqual(['a', 'd'])
    expect(arranged.hiddenCount).toBe(1)
  })

  it('sorts by order, then natural order', () => {
    const view = withView(
      { kind: 'set_display', target: t('d'), patch: { order: 0 } },
      { kind: 'set_display', target: t('b'), patch: { order: 1 } }
    )
    expect(keys(arrangeSignals(rows, view).items)).toEqual(['d', 'b', 'a', 'c'])
  })

  it('collapses a plot group into one item at its first member', () => {
    const view = withView(
      { kind: 'set_display', target: t('b'), patch: { plot_group: 'Shoulder' } },
      { kind: 'set_display', target: t('d'), patch: { plot_group: 'Shoulder' } }
    )
    expect(keys(arrangeSignals(rows, view).items)).toEqual(['a', '[Shoulder:b,d]', 'c'])
  })

  it('does not confuse device ids that contain "/"', () => {
    const view = withView({
      kind: 'set_display',
      target: t('3/a', 'usb:1'),
      patch: { hidden: true }
    })
    expect(keys(arrangeSignals(rows, view).items)).toEqual(['a', 'b', 'c', 'd'])
  })
})

describe('pinned and hidden entries', () => {
  it('lists pinned (not hidden) entries by order, and hidden entries', () => {
    const view = withView(
      { kind: 'set_display', target: t('a'), patch: { pinned: true, order: 5 } },
      { kind: 'set_display', target: t('b'), patch: { pinned: true, order: 1 } },
      { kind: 'set_display', target: t('c'), patch: { pinned: true, hidden: true } }
    )
    expect(pinnedEntries(view).map((e) => (e.target as SignalTarget).signal)).toEqual(['b', 'a'])
    expect(hiddenEntries(view).map((e) => (e.target as SignalTarget).signal)).toEqual(['c'])
  })
})

describe('reorderOps', () => {
  const item = (signal: string, order: number | null = null): OrderedMember[] => [
    { target: t(signal), order }
  ]

  it('gives every item up to the moved one an explicit order, sending only changes', () => {
    const ops = reorderOps([item('a', 0), item('b'), item('c')], 2, 0)
    expect(ops).toEqual([
      { kind: 'set_display', target: t('c'), patch: { order: 0 } },
      { kind: 'set_display', target: t('a'), patch: { order: 1 } },
      { kind: 'set_display', target: t('b'), patch: { order: 2 } }
    ])
  })

  it('moves every member of a plot group together', () => {
    const group = [
      { target: t('b'), order: null },
      { target: t('c'), order: null }
    ]
    const ops = reorderOps([item('a', 0), group], 1, 0)
    expect(ops.map((op) => [(op.target as SignalTarget).signal, op.patch.order])).toEqual([
      ['b', 0],
      ['c', 0],
      ['a', 1]
    ])
  })

  it('is empty for a no-op move or an out-of-range index', () => {
    expect(reorderOps([item('a'), item('b')], 1, 1)).toEqual([])
    expect(reorderOps([item('a')], 0, 5)).toEqual([])
  })
})
