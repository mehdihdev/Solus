// SOLUSDEV-319 — a signal card reads the team-shared view: unit, axis limits, ⋯ menu,
// and derived cards keep the shared name (wireflow live-bench-view.md §1, §8).
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { EMPTY_BENCH_VIEW, type BenchView, type SignalTarget } from '@solus/shared-types'
import { SignalWidget } from './SignalWidget'
import { BenchViewContext } from './view/BenchViewContext'
import { applyDisplayOps } from './view/viewOps'

const target: SignalTarget = { kind: 'signal', device_id: 'usb:1/3', signal: 'position' }
const series = {
  signal: 'position',
  points: [
    { timestamp: '2026-09-14T12:00:00Z', value: 0, unit: 'rad' },
    { timestamp: '2026-09-14T12:00:01Z', value: Math.PI, unit: 'rad' }
  ]
}
function renderCard(view: BenchView, canEdit = true, props = {}): void {
  render(
    <BenchViewContext.Provider value={{ projectId: 'p1', view, canEdit, devices: {} }}>
      <SignalWidget userId="u" projectId="p1" deviceId="usb:1/3" series={series} {...props} />
    </BenchViewContext.Provider>
  )
}

describe('shared view on a signal card', () => {
  it('shows the team unit converted from the packet unit', () => {
    renderCard(
      applyDisplayOps(EMPTY_BENCH_VIEW, [{ kind: 'set_display', target, patch: { unit: 'deg' } }])
    )
    expect(screen.getByLabelText('position value')).toHaveTextContent(/180\.0\s*deg/)
  })

  it('falls back to the packet unit when the team unit is not convertible', () => {
    renderCard(
      applyDisplayOps(EMPTY_BENCH_VIEW, [{ kind: 'set_display', target, patch: { unit: 'mA' } }])
    )
    expect(screen.getByLabelText('position value')).toHaveTextContent(/3\.142\s*rad/)
  })

  it('draws fixed axis limits on the plot', () => {
    renderCard(
      applyDisplayOps(EMPTY_BENCH_VIEW, [
        { kind: 'set_display', target, patch: { limits: { min: -1, max: 4 } } }
      ])
    )
    expect(screen.getByLabelText('Axis max 4')).toBeInTheDocument()
    expect(screen.getByLabelText('Axis min -1')).toBeInTheDocument()
  })

  it('offers the ⋯ menu to a member and not to a viewer', () => {
    renderCard(EMPTY_BENCH_VIEW)
    expect(screen.getByRole('button', { name: 'View options for position' })).toBeInTheDocument()
  })

  it('a viewer gets no menu', () => {
    renderCard(EMPTY_BENCH_VIEW, false)
    expect(screen.queryByRole('button', { name: /View options/ })).not.toBeInTheDocument()
  })

  it('a derived card shows its shared name without a local rename', () => {
    renderCard(EMPTY_BENCH_VIEW, true, {
      deviceId: 'derived:d1',
      target: { kind: 'derived', id: 'd1' },
      series: { signal: 'Lift error', points: [] }
    })
    expect(screen.getByText('Lift error')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rename Lift error' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Lift error value')).toHaveTextContent('— (no data)')
  })
})
