// SOLUSDEV-319 — the ⋯ menu on a signal card / derived row (wireflow live-bench-view.md §1, §8).
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EMPTY_BENCH_VIEW, type BenchView, type SignalTarget } from '@solus/shared-types'
import { BenchViewContext } from './BenchViewContext'
import { resetBenchViewStore, useBenchViewStore } from './useBenchView'
import { applyDisplayOps } from './viewOps'
import { ViewControls } from './ViewControls'

const target: SignalTarget = { kind: 'signal', device_id: 'usb:1/3', signal: 'pos' }
const setDisplay = vi.fn(async () => ({ ok: true as const, version: 1, inverseOps: [] }))

function renderControls(
  props: Partial<React.ComponentProps<typeof ViewControls>> = {},
  { canEdit = true, view = EMPTY_BENCH_VIEW }: { canEdit?: boolean; view?: BenchView } = {}
): void {
  render(
    <BenchViewContext.Provider value={{ projectId: 'p1', view, canEdit, devices: {} }}>
      <ViewControls target={target} label="pos" packetUnit="rad" {...props} />
    </BenchViewContext.Provider>
  )
}
const open = (): void => {
  fireEvent.click(screen.getByRole('button', { name: 'View options for pos' }))
}
const sent = (): unknown => (setDisplay.mock.calls.at(-1) as unknown[] | undefined)?.[1]

beforeEach(() => {
  resetBenchViewStore()
  setDisplay.mockClear()
  useBenchViewStore.setState({ setDisplay })
})

describe('member', () => {
  it('pins and hides through set_display', () => {
    renderControls()
    open()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Pin' }))
    expect(sent()).toEqual([{ kind: 'set_display', target, patch: { pinned: true } }])
    open()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Hide' }))
    expect(sent()).toEqual([{ kind: 'set_display', target, patch: { hidden: true } }])
  })

  it('offers Unpin for a pinned target', () => {
    const view = applyDisplayOps(EMPTY_BENCH_VIEW, [
      { kind: 'set_display', target, patch: { pinned: true } }
    ])
    renderControls({}, { view })
    open()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Unpin' }))
    expect(sent()).toEqual([{ kind: 'set_display', target, patch: { pinned: null } }])
  })

  it('sets the shared unit within the packet unit family only', () => {
    renderControls()
    open()
    const select = screen.getByLabelText('Unit for pos')
    expect([...(select as HTMLSelectElement).options].map((o) => o.value)).toEqual(['rad', 'deg'])
    fireEvent.change(select, { target: { value: 'deg' } })
    expect(sent()).toEqual([{ kind: 'set_display', target, patch: { unit: 'deg' } }])
  })

  it('sets an axis range, refuses min >= max inline, and Auto clears it', () => {
    renderControls()
    open()
    fireEvent.change(screen.getByLabelText('Axis min for pos'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Axis max for pos'), { target: { value: '1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply range' }))
    expect(screen.getByRole('alert')).toHaveTextContent(/min must be below max/i)
    expect(setDisplay).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Axis min for pos'), { target: { value: '-1.6' } })
    fireEvent.change(screen.getByLabelText('Axis max for pos'), { target: { value: '1.6' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply range' }))
    expect(sent()).toEqual([
      { kind: 'set_display', target, patch: { limits: { min: -1.6, max: 1.6 } } }
    ])
    open()
    fireEvent.click(screen.getByRole('button', { name: 'Auto' }))
    expect(sent()).toEqual([{ kind: 'set_display', target, patch: { limits: null } }])
  })

  it('joins an existing group, makes a new one, or leaves', () => {
    const other: SignalTarget = { ...target, signal: 'goal' }
    const view = applyDisplayOps(EMPTY_BENCH_VIEW, [
      { kind: 'set_display', target: other, patch: { plot_group: 'Shoulder' } }
    ])
    renderControls({}, { view })
    open()
    fireEvent.change(screen.getByLabelText('Plot group for pos'), { target: { value: 'Shoulder' } })
    expect(sent()).toEqual([{ kind: 'set_display', target, patch: { plot_group: 'Shoulder' } }])
    open()
    fireEvent.change(screen.getByLabelText('New plot group for pos'), {
      target: { value: 'Wrist' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create group' }))
    expect(sent()).toEqual([{ kind: 'set_display', target, patch: { plot_group: 'Wrist' } }])
  })

  it('shows a write refusal inline under the menu', () => {
    useBenchViewStore.setState({
      projects: {
        p1: { view: null, status: 'ready', lastEdit: null, notice: 'At most 16 plot groups.' }
      }
    })
    renderControls()
    open()
    expect(screen.getByRole('alert')).toHaveTextContent('At most 16 plot groups.')
  })

  it('offers Edit and Delete for a derived row', () => {
    const onEdit = vi.fn()
    const onDelete = vi.fn()
    renderControls({
      target: { kind: 'derived', id: 'd1' },
      packetUnit: null,
      derived: { expression: '1', onEdit, onDelete }
    })
    open()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Edit' }))
    expect(onEdit).toHaveBeenCalled()
    open()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    expect(onDelete).toHaveBeenCalled()
  })
})

describe('viewer', () => {
  it('has no menu on a signal card', () => {
    renderControls({}, { canEdit: false })
    expect(screen.queryByRole('button', { name: 'View options for pos' })).not.toBeInTheDocument()
  })

  it('sees only Copy expression on a derived row', () => {
    const writeText = vi.fn(async () => undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    renderControls(
      {
        target: { kind: 'derived', id: 'd1' },
        derived: { expression: 'sig("a", "b")', onEdit: vi.fn(), onDelete: vi.fn() }
      },
      { canEdit: false }
    )
    open()
    expect(screen.getAllByRole('menuitem').map((item) => item.textContent)).toEqual([
      'Copy expression'
    ])
    expect(screen.queryByLabelText(/Unit for/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Copy expression' }))
    expect(writeText).toHaveBeenCalledWith('sig("a", "b")')
  })
})
