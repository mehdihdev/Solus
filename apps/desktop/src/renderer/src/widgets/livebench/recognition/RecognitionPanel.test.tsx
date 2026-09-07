// RBT-03: the user CONFIRMS, never authors — and nothing is ever auto-accepted.
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { RecognitionPanel } from './RecognitionPanel'
import {
  TIER1_BUS_FIRMWARE_REPO,
  TIER2_FIRMWARE_ONLY,
  TIER3_BARE_SERIAL,
  TIER4_ROS_BONUS
} from './proposals.constants'

afterEach(cleanup)

describe('RecognitionPanel', () => {
  it.each([
    ['tier 1', TIER1_BUS_FIRMWARE_REPO],
    ['tier 2', TIER2_FIRMWARE_ONLY],
    ['tier 3', TIER3_BARE_SERIAL],
    ['tier 4', TIER4_ROS_BONUS]
  ])('%s renders a usable screen', (_label, proposals) => {
    render(<RecognitionPanel proposals={proposals} onDecision={vi.fn()} />)

    expect(screen.getAllByRole('row').length).toBeGreaterThan(proposals.length)
    expect(screen.getByRole('button', { name: /accept all/i })).toBeInTheDocument()
  })

  it('never auto-accepts — even a 0.92 bus-enumerated row starts as proposed', () => {
    const onDecision = vi.fn()
    render(<RecognitionPanel proposals={TIER1_BUS_FIRMWARE_REPO} onDecision={onDecision} />)

    expect(onDecision).not.toHaveBeenCalled()
    expect(screen.getAllByText('proposed').length).toBe(TIER1_BUS_FIRMWARE_REPO.length)
  })

  it('accepts a single row with one click and reports the decision', () => {
    const onDecision = vi.fn()
    render(<RecognitionPanel proposals={TIER1_BUS_FIRMWARE_REPO} onDecision={onDecision} />)

    const row = screen.getByTestId('proposal-bus:demo/3')
    fireEvent.click(within(row).getByRole('button', { name: /^accept$/i }))

    expect(onDecision).toHaveBeenCalledWith('bus:demo/3', { kind: 'accept' })
    expect(within(row).getByText('accepted')).toBeInTheDocument()
  })

  it('rejecting is as cheap as accepting — one click', () => {
    const onDecision = vi.fn()
    render(<RecognitionPanel proposals={TIER1_BUS_FIRMWARE_REPO} onDecision={onDecision} />)

    const row = screen.getByTestId('proposal-bus:demo/7')
    fireEvent.click(within(row).getByRole('button', { name: /reject/i }))

    expect(onDecision).toHaveBeenCalledWith('bus:demo/7', { kind: 'reject' })
    expect(within(row).getByText('rejected')).toBeInTheDocument()
  })

  it('accept-all accepts proposed rows and NEVER touches unknowns', () => {
    const onDecision = vi.fn()
    const mixed = [...TIER2_FIRMWARE_ONLY, ...TIER3_BARE_SERIAL]
    render(<RecognitionPanel proposals={mixed} onDecision={onDecision} />)

    fireEvent.click(screen.getByRole('button', { name: /accept all/i }))

    expect(onDecision).toHaveBeenCalledTimes(TIER2_FIRMWARE_ONLY.length)
    for (const unknown of TIER3_BARE_SERIAL) {
      expect(onDecision).not.toHaveBeenCalledWith(unknown.id, { kind: 'accept' })
    }
  })

  it('unknown rows are explicitly unknown and have no accept button', () => {
    render(<RecognitionPanel proposals={TIER3_BARE_SERIAL} onDecision={vi.fn()} />)

    const row = screen.getByTestId('proposal-serial:demo/ch0')
    expect(within(row).getByText('unknown')).toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: /^accept$/i })).toBeNull()
  })

  it('tier 3 flow: the user NAMES an unknown channel (edit decision)', () => {
    const onDecision = vi.fn()
    render(<RecognitionPanel proposals={TIER3_BARE_SERIAL} onDecision={onDecision} />)

    const row = screen.getByTestId('proposal-serial:demo/ch2')
    fireEvent.change(within(row).getByRole('textbox'), { target: { value: 'shoulder' } })
    fireEvent.click(within(row).getByRole('button', { name: /save/i }))

    expect(onDecision).toHaveBeenCalledWith('serial:demo/ch2', {
      kind: 'edit',
      functionName: 'shoulder'
    })
    expect(within(row).getByText('edited')).toBeInTheDocument()
  })

  it('editing a PROPOSED row renames it — as cheap as accepting', () => {
    const onDecision = vi.fn()
    render(<RecognitionPanel proposals={TIER2_FIRMWARE_ONLY} onDecision={onDecision} />)

    const row = screen.getByTestId('proposal-pin:9')
    fireEvent.change(within(row).getByRole('textbox'), { target: { value: 'forearm' } })
    fireEvent.click(within(row).getByRole('button', { name: /save/i }))

    expect(onDecision).toHaveBeenCalledWith('pin:9', { kind: 'edit', functionName: 'forearm' })
  })

  it('shows confidence honestly and reveals evidence with its note on expand', () => {
    render(<RecognitionPanel proposals={TIER2_FIRMWARE_ONLY} onDecision={vi.fn()} />)

    const row = screen.getByTestId('proposal-pin:9')
    expect(within(row).getByText(/55%/)).toBeInTheDocument()
    fireEvent.click(within(row).getByText(/evidence/i))
    expect(within(row).getByText(/code intent only/)).toBeInTheDocument()
    expect(within(row).getByText(/src\/firmware\.cpp:11/)).toBeInTheDocument()
  })

  it('saving an empty name does nothing — an unknown cannot be silently blanked in', () => {
    const onDecision = vi.fn()
    render(<RecognitionPanel proposals={TIER3_BARE_SERIAL} onDecision={onDecision} />)

    const row = screen.getByTestId('proposal-serial:demo/ch1')
    fireEvent.click(within(row).getByRole('button', { name: /save/i }))

    expect(onDecision).not.toHaveBeenCalled()
    expect(within(row).getByText('unknown')).toBeInTheDocument()
  })

  it('renders an optional extra cell per row, keyed to the proposal', () => {
    render(
      <RecognitionPanel
        proposals={TIER1_BUS_FIRMWARE_REPO}
        onDecision={vi.fn()}
        renderRowExtra={(proposal) => (
          <select aria-label={`category for ${proposal.subject}`}>
            <option>actuators</option>
          </select>
        )}
      />
    )

    expect(screen.getByRole('combobox', { name: 'category for servo at address 3' })).toBeVisible()
    expect(screen.getAllByRole('combobox')).toHaveLength(TIER1_BUS_FIRMWARE_REPO.length)
    expect(screen.getAllByRole('columnheader')).toHaveLength(5)
  })
})
