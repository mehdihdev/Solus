// SOLUSDEV-319 — pinned strip, Derived panel, Hidden signals and the Undo toast
// (wireflow live-bench-view.md "Layout", §1.2, §2.5, §8).
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EMPTY_BENCH_VIEW, type BenchView, type BenchViewDerived } from '@solus/shared-types'
import type { BenchDeviceRecent } from '../../../lib/api/resources'
import { BenchViewContext } from './BenchViewContext'
import { BenchViewBottom, BenchViewTop } from './BenchViewPanels'
import { resetBenchViewStore, useBenchViewStore, type ProjectBenchView } from './useBenchView'
import { applyDisplayOps } from './viewOps'

const DEVICE = 'usb:1/3'
const devices: Record<string, BenchDeviceRecent> = {
  [DEVICE]: {
    device_id: DEVICE,
    resolved_entity_id: null,
    signals: [
      {
        signal: 'pos',
        points: [
          { timestamp: '2026-10-31T00:00:00Z', value: 1, unit: 'rad' },
          { timestamp: '2026-10-31T00:00:01Z', value: 2, unit: 'rad' }
        ]
      }
    ]
  }
}
const lift: BenchViewDerived = {
  id: 'd1',
  name: 'Lift error',
  expression: `sig("${DEVICE}", "pos") * 2`,
  unit: 'deg',
  node_count: 3,
  refs: [{ device_id: DEVICE, signal: 'pos' }],
  created_at: '',
  updated_at: ''
}
const grip: BenchViewDerived = {
  ...lift,
  id: 'd2',
  name: 'Grip load',
  expression: 'sig("gone", "x")',
  refs: [{ device_id: 'gone', signal: 'x' }]
}
const base: BenchView = { ...EMPTY_BENCH_VIEW, version: 3, derived: [lift, grip] }
const saveDerived = vi.fn(async () => ({ ok: true as const, version: 4, inverseOps: [] }))
const undo = vi.fn()
const setDisplay = vi.fn(async () => ({ ok: true as const, version: 4, inverseOps: [] }))

function seed(view: BenchView, extra: Partial<ProjectBenchView> = {}): void {
  useBenchViewStore.setState({
    projects: { p1: { view, status: 'ready', lastEdit: null, notice: null, ...extra } }
  })
}
function renderPanels(view: BenchView, canEdit = true): void {
  render(
    <BenchViewContext.Provider value={{ projectId: 'p1', view, canEdit, devices }}>
      <BenchViewTop />
      <BenchViewBottom />
    </BenchViewContext.Provider>
  )
}

beforeEach(() => {
  resetBenchViewStore()
  vi.clearAllMocks()
  useBenchViewStore.setState({ saveDerived, undo, setDisplay })
  seed(base)
})
afterEach(() => vi.useRealTimers())

describe('pinned strip', () => {
  it('appears only with a pinned target and lists pinned signals and derived by order', () => {
    const view = applyDisplayOps(base, [
      {
        kind: 'set_display',
        target: { kind: 'signal', device_id: DEVICE, signal: 'pos' },
        patch: { pinned: true, order: 1 }
      },
      {
        kind: 'set_display',
        target: { kind: 'derived', id: 'd1' },
        patch: { pinned: true, order: 0 }
      }
    ])
    renderPanels(view)
    const strip = screen.getByRole('region', { name: 'Pinned' })
    expect(
      within(strip)
        .getAllByRole('region')
        .map((card) => card.getAttribute('aria-label'))
    ).toEqual(['Lift error signal', 'pos signal'])
    expect(within(strip).getByLabelText('pos value')).toHaveTextContent(/2\.000\s*rad/)
  })

  it('is absent with nothing pinned', () => {
    renderPanels(base)
    expect(screen.queryByRole('region', { name: 'Pinned' })).not.toBeInTheDocument()
  })
})

describe('Derived panel', () => {
  it('renders derived signals as cards with live values and "no data" when inputs are missing', () => {
    renderPanels(base)
    const panel = screen.getByRole('region', { name: 'Derived' })
    expect(within(panel).getByLabelText('Lift error value')).toHaveTextContent(/4\.0\s*deg/)
    expect(within(panel).getByLabelText('Grip load value')).toHaveTextContent('— (no data)')
  })

  it('+ Derived signal opens the editor', () => {
    renderPanels(base)
    fireEvent.click(screen.getByRole('button', { name: '+ Derived signal' }))
    expect(screen.getByRole('dialog', { name: 'Derived signal' })).toBeInTheDocument()
  })

  it('Delete asks to confirm, then sends delete_derived', async () => {
    renderPanels(base)
    fireEvent.click(screen.getByRole('button', { name: 'View options for Lift error' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    const confirm = screen.getByRole('alertdialog')
    expect(confirm).toHaveTextContent('Delete Lift error? Charts that use it lose it.')
    await act(async () => fireEvent.click(within(confirm).getByRole('button', { name: 'Delete' })))
    expect(saveDerived).toHaveBeenCalledWith('p1', [{ kind: 'delete_derived', id: 'd1' }])
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })
})

describe('Hidden signals', () => {
  const view = applyDisplayOps(base, [
    {
      kind: 'set_display',
      target: { kind: 'signal', device_id: DEVICE, signal: 'pos' },
      patch: { hidden: true }
    },
    { kind: 'set_display', target: { kind: 'derived', id: 'd2' }, patch: { hidden: true } }
  ])

  it('lists hidden targets and Show un-hides one', () => {
    renderPanels(view)
    expect(screen.queryByLabelText('Grip load value')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Hidden signals (2)' }))
    const list = screen.getByRole('list', { name: 'Hidden signals' })
    expect(
      within(list)
        .getAllByRole('listitem')
        .map((item) => item.textContent)
    ).toEqual([`${DEVICE} · posShow`, 'Grip loadShow'])
    fireEvent.click(within(list).getAllByRole('button', { name: 'Show' })[0])
    expect(setDisplay).toHaveBeenCalledWith('p1', [
      {
        kind: 'set_display',
        target: { kind: 'signal', device_id: DEVICE, signal: 'pos' },
        patch: { hidden: null }
      }
    ])
  })

  it('a viewer sees the list without Show', () => {
    renderPanels(view, false)
    fireEvent.click(screen.getByRole('button', { name: 'Hidden signals (2)' }))
    expect(screen.queryByRole('button', { name: 'Show' })).not.toBeInTheDocument()
  })
})

describe('Undo toast', () => {
  it('offers Undo for 6 s after the user’s own edit and sends the inverse ops', async () => {
    vi.useFakeTimers()
    const lastEdit = { version: 4, inverseOps: [{ kind: 'delete_derived' as const, id: 'd9' }] }
    undo.mockResolvedValue({ ok: true, version: 5, inverseOps: [] })
    seed(base, { lastEdit: { ...lastEdit, at: Date.now() } })
    renderPanels(base)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Undo' })))
    expect(undo).toHaveBeenCalledWith('p1', lastEdit)
  })

  it('reads "View changed since" on a 409 Undo', async () => {
    undo.mockResolvedValue({ ok: false, failure: { kind: 'conflict', currentVersion: 6 } })
    seed(base, { lastEdit: { version: 4, inverseOps: [], at: Date.now() } })
    renderPanels(base)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Undo' })))
    expect(screen.getByText('View changed since — Undo unavailable')).toBeInTheDocument()
  })

  it('disappears after 6 s', () => {
    vi.useFakeTimers()
    seed(base, { lastEdit: { version: 4, inverseOps: [], at: Date.now() } })
    renderPanels(base)
    act(() => vi.advanceTimersByTime(6_100))
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument()
  })
})

describe('viewer', () => {
  it('has no + Derived signal, no Undo, and only Copy expression on derived rows', () => {
    seed(base, { lastEdit: { version: 4, inverseOps: [], at: Date.now() } })
    renderPanels(base, false)
    expect(screen.queryByRole('button', { name: '+ Derived signal' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'View options for Lift error' }))
    expect(screen.getAllByRole('menuitem').map((item) => item.textContent)).toEqual([
      'Copy expression'
    ])
  })
})
