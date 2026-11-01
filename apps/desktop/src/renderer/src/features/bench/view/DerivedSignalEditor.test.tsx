// SOLUSDEV-319 — the derived-signal side sheet (wireflow live-bench-view.md §2, §3.2, §4.2).
import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EMPTY_BENCH_VIEW, type BenchView, type BenchViewDerived } from '@solus/shared-types'
import type { BenchDeviceRecent } from '../../../lib/api/resources'
import { DerivedSignalEditor } from './DerivedSignalEditor'
import { resetBenchViewStore, useBenchViewStore, type BenchViewWriteOutcome } from './useBenchView'

const DEVICE = 'usb:5A7A/3'
const devices: Record<string, BenchDeviceRecent> = {
  [DEVICE]: {
    device_id: DEVICE,
    resolved_entity_id: null,
    signals: [
      {
        signal: 'goal',
        points: [
          { timestamp: '2026-10-31T00:00:00Z', value: 2, unit: 'deg' },
          { timestamp: '2026-10-31T00:00:01Z', value: 5, unit: 'deg' }
        ]
      }
    ]
  }
}
const derived: BenchViewDerived = {
  id: 'd1',
  name: 'Lift error',
  expression: `sig("${DEVICE}", "goal") * 2`,
  unit: 'deg',
  node_count: 3,
  refs: [{ device_id: DEVICE, signal: 'goal' }],
  created_at: '2026-10-31T00:00:00Z',
  updated_at: '2026-10-31T00:00:00Z'
}
const saveDerived = vi.fn<(...args: unknown[]) => Promise<BenchViewWriteOutcome>>()
const load = vi.fn(async () => undefined)

function seed(view: BenchView): void {
  useBenchViewStore.setState({
    projects: { p1: { view, status: 'ready', lastEdit: null, notice: null } }
  })
}
function renderEditor(derivedId: string | null = null, onClose = vi.fn()): typeof onClose {
  render(
    <DerivedSignalEditor projectId="p1" devices={devices} derivedId={derivedId} onClose={onClose} />
  )
  return onClose
}
const expression = (): HTMLTextAreaElement =>
  screen.getByLabelText('Expression') as HTMLTextAreaElement
const type = (text: string): void => {
  fireEvent.change(expression(), { target: { value: text } })
}

beforeEach(() => {
  resetBenchViewStore()
  saveDerived.mockReset()
  load.mockClear()
  useBenchViewStore.setState({ saveDerived, load })
  seed({ ...EMPTY_BENCH_VIEW, version: 3, derived: [derived] })
})

describe('DerivedSignalEditor', () => {
  it('underlines the parse error span with the fixed sentence for its code', () => {
    renderEditor()
    type(`sig("${DEVICE}", "goal") + nope(1)`)
    expect(screen.getByRole('alert')).toHaveTextContent('Unknown function.')
    expect(screen.getByTestId('expression-error-span')).toHaveTextContent('nope')
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
  })

  it('counts nodes and signals and previews the draft on the live streams', () => {
    renderEditor()
    type(`sig("${DEVICE}", "goal") * 2`)
    expect(screen.getByText('3 / 64 nodes · 1 / 8 signals')).toBeInTheDocument()
    expect(screen.getByLabelText('Preview value')).toHaveTextContent('10')
  })

  it('warns when a referenced signal has no data yet', () => {
    renderEditor()
    type(`sig("${DEVICE}", "positon")`)
    expect(screen.getByText(/No data yet for this signal/)).toBeInTheDocument()
  })

  it('inserts a correctly quoted reference for a streaming signal', () => {
    renderEditor()
    fireEvent.change(screen.getByLabelText('Insert signal'), {
      target: { value: JSON.stringify([DEVICE, 'goal']) }
    })
    expect(expression().value).toBe(`sig("${DEVICE}", "goal")`)
  })

  it('saves a new signal as upsert_derived and closes', async () => {
    saveDerived.mockResolvedValue({ ok: true, version: 4, inverseOps: [] })
    const onClose = renderEditor()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Double goal' } })
    fireEvent.change(screen.getByLabelText('Unit'), { target: { value: 'deg' } })
    type(`sig("${DEVICE}", "goal") * 2`)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })))
    expect(saveDerived).toHaveBeenCalledWith('p1', [
      {
        kind: 'upsert_derived',
        name: 'Double goal',
        expression: `sig("${DEVICE}", "goal") * 2`,
        unit: 'deg'
      }
    ])
    expect(onClose).toHaveBeenCalled()
  })

  it('edits an existing signal under its id', async () => {
    saveDerived.mockResolvedValue({ ok: true, version: 4, inverseOps: [] })
    renderEditor('d1')
    expect(expression().value).toBe(derived.expression)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })))
    expect(saveDerived.mock.calls[0][1]).toEqual([
      {
        kind: 'upsert_derived',
        id: 'd1',
        name: 'Lift error',
        expression: derived.expression,
        unit: 'deg'
      }
    ])
  })

  it('keeps the sheet open with the server error position on expression_error', async () => {
    saveDerived.mockResolvedValue({
      ok: false,
      failure: {
        kind: 'expression',
        details: [{ op_index: 0, code: 'too_deep', position: 0, length: 3, message: 'Too deep.' }]
      }
    })
    const onClose = renderEditor('d1')
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })))
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('Too deep.')
    expect(screen.getByTestId('expression-error-span')).toHaveTextContent('sig')
    expect(expression().value).toBe(derived.expression)
  })

  it('marks the Name field on duplicate_name', async () => {
    saveDerived.mockResolvedValue({
      ok: false,
      failure: {
        kind: 'refused',
        code: 'duplicate_name',
        message: 'That name is taken.',
        status: 422
      }
    })
    renderEditor('d1')
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })))
    expect(screen.getByLabelText('Name')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText('That name is taken.')).toBeInTheDocument()
  })

  it('never retries a 409; offers Reload with the text intact', async () => {
    saveDerived.mockResolvedValue({ ok: false, failure: { kind: 'conflict', currentVersion: 5 } })
    renderEditor('d1')
    type('1 + sig("a", "b")')
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })))
    expect(saveDerived).toHaveBeenCalledTimes(1)
    expect(
      screen.getByText('A teammate changed the bench view. Reload to see it, then save again.')
    ).toBeInTheDocument()
    expect(expression().value).toBe('1 + sig("a", "b")')
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }))
    expect(load).toHaveBeenCalledWith('p1')
  })

  it('shows the teammate banner when the signal changes underneath, and Reload adopts it', () => {
    renderEditor('d1')
    type('1 + sig("a", "b")')
    act(() =>
      seed({
        ...EMPTY_BENCH_VIEW,
        version: 4,
        derived: [{ ...derived, expression: 'sig("x", "y")', updated_at: '2026-10-31T01:00:00Z' }]
      })
    )
    expect(screen.getByText('Changed by a teammate')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }))
    expect(expression().value).toBe('sig("x", "y")')
    expect(screen.queryByText('Changed by a teammate')).not.toBeInTheDocument()
  })

  it('Keep editing dismisses the banner and keeps the draft', () => {
    renderEditor('d1')
    type('1 + sig("a", "b")')
    act(() => seed({ ...EMPTY_BENCH_VIEW, version: 4, derived: [] }))
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }))
    expect(expression().value).toBe('1 + sig("a", "b")')
    expect(screen.queryByText('Changed by a teammate')).not.toBeInTheDocument()
  })
})
