// SOLUSDEV-319: the Ember Pill plan card — parked approvals shown as one plan
// with every concrete diff, run ONE AT A TIME through the normal decision call
// (each keeps its own staleness re-check), stopped at the first failure.
import { describe, it, expect, vi } from 'vitest'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import type { PendingConfirmation } from '../../lib/api/solStream'
import { PlanCard } from './PlanCard'

const step = (id: string, summary: string, before: string, after: string): PendingConfirmation => ({
  confirmationId: id,
  tool: 'kicad.set_symbol_property',
  summary,
  preview: [{ label: `${id} · Value`, before, after }]
})

const STEPS = [
  step('r1', 'Set R1 to 10k', '4.7k', '10k'),
  step('r2', 'Set R2 to 4k7', '1k', '4k7'),
  step('r3', 'Set R3 to 1k', '100', '1k')
]

function deferred(): { promise: Promise<void>; resolve: () => void; reject: (e: Error) => void } {
  let resolve!: () => void
  let reject!: (e: Error) => void
  const promise = new Promise<void>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('PlanCard', () => {
  it('lists every step with its summary and its verbatim before → after rows', () => {
    render(<PlanCard steps={STEPS} onDecide={vi.fn()} onShowMe={vi.fn()} />)
    expect(screen.getByText('PLAN · 3 STEPS')).toBeInTheDocument()
    const plan = screen.getByRole('list', { name: 'Plan steps' })
    expect(within(plan).getAllByRole('listitem')).toHaveLength(3)
    expect(screen.getByText('Set R2 to 4k7')).toBeInTheDocument()
    expect(screen.getByText('4.7k')).toBeInTheDocument()
    expect(screen.getByText('4k7')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run 3 steps' })).toBeInTheDocument()
  })

  it('a one-step plan says so in the singular', () => {
    render(<PlanCard steps={STEPS.slice(0, 1)} onDecide={vi.fn()} onShowMe={vi.fn()} />)
    expect(screen.getByText('PLAN · 1 STEP')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run 1 step' })).toBeInTheDocument()
  })

  it('runs the steps one at a time, in order, each awaited before the next', async () => {
    const pending = STEPS.map(() => deferred())
    const onDecide = vi.fn(
      (id: string) => pending[STEPS.findIndex((s) => s.confirmationId === id)].promise
    )
    render(<PlanCard steps={STEPS} onDecide={onDecide} onShowMe={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Run 3 steps' }))
    expect(onDecide).toHaveBeenCalledTimes(1)
    expect(onDecide).toHaveBeenLastCalledWith('r1', 'approve')
    expect(screen.getByText('APPLYING · STEP 1 OF 3')).toBeInTheDocument()
    await act(async () => pending[0].resolve())
    expect(onDecide).toHaveBeenCalledTimes(2)
    expect(onDecide).toHaveBeenLastCalledWith('r2', 'approve')
    expect(screen.getByText('APPLYING · STEP 2 OF 3')).toBeInTheDocument()
    await act(async () => pending[1].resolve())
    await act(async () => pending[2].resolve())
    expect(onDecide.mock.calls.map((c) => c[0])).toEqual(['r1', 'r2', 'r3'])
    expect(screen.queryByText(/APPLYING/)).not.toBeInTheDocument()
  })
})

describe('PlanCard running', () => {
  it('a second click while running sends nothing more', async () => {
    const first = deferred()
    const onDecide = vi.fn(() => first.promise)
    render(<PlanCard steps={STEPS} onDecide={onDecide} onShowMe={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Run 3 steps' }))
    expect(screen.queryByRole('button', { name: 'Run 3 steps' })).not.toBeInTheDocument()
    expect(onDecide).toHaveBeenCalledTimes(1)
  })

  it('Stop lets the in-flight step finish and leaves the rest parked', async () => {
    const first = deferred()
    const onDecide = vi.fn(() => first.promise)
    render(<PlanCard steps={STEPS} onDecide={onDecide} onShowMe={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Run 3 steps' }))
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    await act(async () => first.resolve())
    expect(onDecide).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Run 3 steps' })).toBeInTheDocument()
  })
})

describe('PlanCard failures and declines', () => {
  it('the first failure stops the run and shows the server reason', async () => {
    const onDecide = vi.fn(async (id: string) => {
      if (id === 'r2') {
        const refused = new Error('What this would do has changed.')
        refused.name = 'ConfirmationRefused'
        throw refused
      }
    })
    render(<PlanCard steps={STEPS} onDecide={onDecide} onShowMe={vi.fn()} />)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Run 3 steps' })))
    expect(onDecide.mock.calls.map((c) => c[0])).toEqual(['r1', 'r2'])
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('What this would do has changed.')
    expect(alert).toHaveTextContent('can’t be retried')
  })

  it('a refused step is left out of the next run', async () => {
    const onDecide = vi.fn(async (id: string) => {
      if (id === 'r1') {
        const refused = new Error('Expired.')
        refused.name = 'ConfirmationRefused'
        throw refused
      }
    })
    render(<PlanCard steps={STEPS} onDecide={onDecide} onShowMe={vi.fn()} />)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Run 3 steps' })))
    onDecide.mockClear()
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Run 2 steps' })))
    expect(onDecide.mock.calls.map((c) => c[0])).toEqual(['r2', 'r3'])
  })

  it('a transport failure says the steps are still waiting', async () => {
    const onDecide = vi.fn(async () => {
      throw new Error('Network down.')
    })
    render(<PlanCard steps={STEPS} onDecide={onDecide} onShowMe={vi.fn()} />)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Run 3 steps' })))
    expect(screen.getByRole('alert')).toHaveTextContent('still waiting')
    expect(screen.getByRole('button', { name: 'Run 3 steps' })).toBeInTheDocument()
  })

  it('Reject declines every step; Show me how declines them and asks for Guide', async () => {
    const onDecide = vi.fn(async () => undefined)
    const onShowMe = vi.fn()
    const { rerender } = render(<PlanCard steps={STEPS} onDecide={onDecide} onShowMe={onShowMe} />)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Reject' })))
    expect(onDecide.mock.calls).toEqual([
      ['r1', 'reject'],
      ['r2', 'reject'],
      ['r3', 'reject']
    ])
    expect(onShowMe).not.toHaveBeenCalled()
    onDecide.mockClear()
    rerender(<PlanCard steps={STEPS.slice(1)} onDecide={onDecide} onShowMe={onShowMe} />)
    await act(async () =>
      fireEvent.click(screen.getByRole('button', { name: 'Show me how instead' }))
    )
    expect(onDecide.mock.calls).toEqual([
      ['r2', 'reject'],
      ['r3', 'reject']
    ])
    expect(onShowMe).toHaveBeenCalledTimes(1)
  })
})
