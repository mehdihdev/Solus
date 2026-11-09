// SOLUSDEV-320 P4-T2 — the sidebar panel for one selected edge: what the relation
// carries, rendered as text; Confirm/Decline only while it is still a candidate.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as edgesApi from '../../../lib/api/edges'
import type { Entity, Relation } from '../../../lib/api/resources'
import { EdgePanel } from './EdgePanel'

vi.mock('../../../lib/api/edges', () => ({ confirmEdge: vi.fn(), declineEdge: vi.fn() }))

const entity = (id: string, name: string): Entity => ({
  id,
  type: 'part',
  domain: 'electrical',
  name,
  source_key: id
})
const FROM = entity('a', 'IMU <b>board</b>')
const TO = entity('b', 'Jetson')
const candidate: Relation = {
  id: 'r1',
  type: 'wires',
  from_entity_id: 'a',
  to_entity_id: 'b',
  origin: 'inferred',
  confidence: 0.55,
  domain_pair: 'ee->ee',
  properties: {
    evidence: [{ kind: 'netlist', ref: 'SDA', detail: 'shared net' }, { kind: 'firmware_symbol' }],
    created_by: 'kicad_sync',
    matrix_cell: 'ee->ee',
    checker_results: [{ rule_id: 'i2c.address', severity: 'warning', message: 'address clash' }]
  }
}

function mount(
  relation: Relation,
  parties: { from?: Entity; to?: Entity } = { from: FROM, to: TO }
): { onDecided: ReturnType<typeof vi.fn>; onClose: ReturnType<typeof vi.fn> } {
  const onDecided = vi.fn()
  const onClose = vi.fn()
  render(
    <EdgePanel
      projectId="p1"
      relation={relation}
      from={parties.from}
      to={parties.to}
      onDecided={onDecided}
      onClose={onClose}
    />
  )
  return { onDecided, onClose }
}

beforeEach(() => vi.clearAllMocks())

describe('EdgePanel', () => {
  it('renders the sentence, direction, confidence, origin, evidence and checker rows as text', () => {
    mount(candidate)
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(
      'IMU <b>board</b> wires Jetson, because shared net (netlist SDA; firmware symbol, inferred, 55%)'
    )
    expect(document.querySelector('b')).toBeNull()
    expect(screen.getByText('IMU <b>board</b> → Jetson')).toBeInTheDocument()
    expect(screen.getByText('55%')).toBeInTheDocument()
    expect(screen.getByText('inferred')).toBeInTheDocument()
    expect(screen.getByText('netlist: SDA — shared net')).toBeInTheDocument()
    expect(screen.getByText('firmware symbol:')).toBeInTheDocument()
    expect(screen.getByText('kicad_sync')).toBeInTheDocument()
    expect(screen.getByText('ee->ee')).toBeInTheDocument()
    expect(screen.getByText('i2c.address · warning')).toBeInTheDocument()
    expect(screen.getByText('address clash')).toBeInTheDocument()
  })

  it('falls back to ids, prints unknown checker results as JSON and offers no decision when confirmed', () => {
    mount(
      {
        ...candidate,
        origin: 'manual',
        confidence: 1,
        properties: { checker_results: { odd: true }, confirmed_at: '2026-10-17T10:00:00Z' }
      },
      {}
    )
    expect(screen.getByText('a → b')).toBeInTheDocument()
    expect(screen.getByText('100%')).toBeInTheDocument()
    expect(document.querySelector('pre')).toHaveTextContent('"odd": true')
    expect(screen.queryByRole('button', { name: 'Confirm' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Decline' })).toBeNull()
  })

  it('confirms a candidate and reports the decision', async () => {
    vi.mocked(edgesApi.confirmEdge).mockResolvedValue({ ...candidate, origin: 'manual' })
    const { onDecided } = mount(candidate)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(onDecided).toHaveBeenCalledOnce())
    expect(edgesApi.confirmEdge).toHaveBeenCalledWith('p1', 'r1')
  })

  it('declines a candidate and shows a failure inline without closing', async () => {
    vi.mocked(edgesApi.declineEdge).mockRejectedValue(new Error('Members only'))
    const { onDecided, onClose } = mount(candidate)
    fireEvent.click(screen.getByRole('button', { name: 'Decline' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Members only')
    expect(edgesApi.declineEdge).toHaveBeenCalledWith('p1', 'r1')
    expect(onDecided).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})

// SOLUSDEV-321 P3-T1 — `checker_results` items carry `status` and `at`; only a failure reads as a
// problem, passes fold under one summary and a missing fact reads "could not check".
describe('EdgePanel checker results', () => {
  it('status and at render, pass collapses', () => {
    const at = '2026-10-27T10:00:00Z'
    mount({
      ...candidate,
      properties: {
        checker_results: [
          {
            rule_id: 'pin_in_code_vs_wiring',
            status: 'fail',
            severity: 'critical',
            message: 'pin 9 is not wired',
            at,
            evidence: {}
          },
          { rule_id: 'power_budget', status: 'pass', severity: 'info', message: 'ok', at },
          { rule_id: 'tolerance_stack', status: 'pass', severity: 'info', message: 'ok', at }
        ]
      }
    })
    expect(screen.getByText('pin_in_code_vs_wiring · failed · critical')).toBeVisible()
    expect(screen.getByText('pin 9 is not wired')).toBeVisible()
    const [first] = screen.getAllByText('2026-10-27 10:00 UTC')
    expect(first).toBeVisible()
    expect(first).toHaveAttribute('datetime', at)
    const passed = screen.getByText('2 passed')
    expect(screen.getByText('power_budget · passed')).not.toBeVisible()
    fireEvent.click(passed)
    expect(screen.getByText('power_budget · passed')).toBeVisible()
    expect(screen.getByText('tolerance_stack · passed')).toBeVisible()
  })

  it('unknown_input shows could not check', () => {
    mount({
      ...candidate,
      properties: {
        checker_results: [
          {
            rule_id: 'gains_vs_resonance',
            status: 'unknown_input',
            severity: 'info',
            message: 'resonance_hz unknown; set it in the part limits',
            at: '2026-10-27T10:00:00Z'
          },
          { rule_id: 'cable_length_voltage_drop', status: 'inconclusive', severity: 'warning' }
        ]
      }
    })
    expect(screen.getByText('gains_vs_resonance · could not check')).toBeVisible()
    expect(screen.getByText('resonance_hz unknown; set it in the part limits')).toBeVisible()
    expect(screen.getByText('cable_length_voltage_drop · inconclusive')).toBeVisible()
    expect(screen.queryByText(/passed/)).toBeNull()
  })
})
