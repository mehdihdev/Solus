import { GraphSuggestions } from './GraphSuggestions'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { GraphNavigator, type GraphNavigatorProps } from './GraphNavigator'
import * as edges from '../../../lib/api/edges'
import * as hardware from '../../../lib/api/hardware'
import type { Relation } from '../../../lib/api/resources'
import { useAuthStore } from '../../../store/authStore'
vi.mock('../../../lib/api/hardware', () => ({
  listHardwareSuggestions: vi.fn(),
  acceptHardwareSuggestion: vi.fn(),
  rejectHardwareSuggestion: vi.fn()
}))
vi.mock('../../../lib/api/edges', () => ({
  listEdgeCandidates: vi.fn(),
  confirmEdge: vi.fn(),
  declineEdge: vi.fn()
}))
const proposal: hardware.HardwareSuggestion = {
  id: 'suggestion',
  subject_ref: 'usb:observed',
  subject_kind: 'device',
  candidate_robot_id: 'robot',
  confidence: 0.87,
  tier: 'high',
  evidence: [{ modality: 'bus_enumeration', evidence: { matched: true } }],
  reason: 'Observed identity matches',
  status: 'pending',
  created_at: '2026-09-15',
  decided_at: null
}
const candidate: Relation = {
  id: 'e1',
  type: 'commands',
  from_entity_id: 'code',
  to_entity_id: 'servo',
  origin: 'inferred',
  confidence: 0.55,
  properties: { evidence: [{ kind: 'firmware_symbol', ref: 'fw.ino:3' }] }
}
const props: GraphNavigatorProps = {
  projectId: 'p',
  onSuggestionsChanged: vi.fn(),
  entities: [
    { id: 'robot', name: 'Arm', type: 'physical_robot', domain: 'project', source_key: null },
    { id: 'servo', name: 'Servo 3', type: 'part', domain: 'electrical', source_key: null },
    { id: 'code', name: 'firmware.ino', type: 'code_file', domain: 'code', source_key: null }
  ],
  relations: [],
  positions: { robot: { x: 0, y: 0 }, servo: { x: 400, y: 0 }, code: { x: 0, y: 400 } },
  focusedId: null,
  onSelect: vi.fn(),
  onMove: vi.fn()
}
beforeEach(() => {
  vi.resetAllMocks()
  useAuthStore.setState({ status: 'authenticated', user: { email: 'owner@example.test' } })
  vi.mocked(hardware.listHardwareSuggestions).mockResolvedValue([proposal])
  vi.mocked(hardware.acceptHardwareSuggestion).mockResolvedValue({
    ...proposal,
    status: 'accepted'
  })
  vi.mocked(hardware.rejectHardwareSuggestion).mockResolvedValue({
    ...proposal,
    status: 'rejected'
  })
  vi.mocked(edges.listEdgeCandidates).mockResolvedValue([])
  vi.mocked(edges.confirmEdge).mockResolvedValue({ ...candidate, origin: 'manual', confidence: 1 })
  vi.mocked(edges.declineEdge).mockResolvedValue(candidate)
})
it('floats only actual pending candidates and exposes confidence, evidence and existing decisions', async () => {
  vi.mocked(hardware.listHardwareSuggestions).mockResolvedValue([
    proposal,
    { ...proposal, id: 'foreign', candidate_robot_id: 'elsewhere' },
    { ...proposal, id: 'settled', status: 'accepted' }
  ])
  render(<GraphNavigator {...props} />)
  expect(await screen.findByText('87% confidence')).toBeInTheDocument()
  expect(screen.getAllByText('usb:observed')).toHaveLength(1)
  expect(screen.getByText('Observed identity matches')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Accept link' }))
  await waitFor(() =>
    expect(hardware.acceptHardwareSuggestion).toHaveBeenCalledExactlyOnceWith('p', 'suggestion')
  )
  await waitFor(() => expect(screen.queryByText('87% confidence')).toBeNull())
})
it('retains failed proposals and uses the existing decline endpoint', async () => {
  vi.mocked(hardware.rejectHardwareSuggestion).mockRejectedValueOnce(new Error('private response'))
  render(<GraphNavigator {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Decline link' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save')
  expect(screen.queryByText('private response')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Decline link' }))
  await waitFor(() => expect(screen.queryByText('87% confidence')).toBeNull())
})
it('discards old account requests across a batched A to B to A', async () => {
  let finish!: (value: hardware.HardwareSuggestion[]) => void
  vi.mocked(hardware.listHardwareSuggestions)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
    .mockResolvedValue([])
  render(<GraphNavigator {...props} />)
  act(() => {
    useAuthStore.setState({ user: { email: 'other@example.test' } })
    useAuthStore.setState({ user: { email: 'owner@example.test' } })
  })
  await act(async () => {
    finish([proposal])
  })
  expect(screen.queryByText('87% confidence')).toBeNull()
})

it('keeps multiple pending decisions for one candidate spatially separate', async () => {
  vi.mocked(hardware.listHardwareSuggestions).mockResolvedValue([
    proposal,
    { ...proposal, id: 'second', subject_ref: 'usb:second' }
  ])
  render(<GraphNavigator {...props} />)
  await screen.findByText('usb:second')
  const cards = screen.getAllByRole('complementary', { name: 'Suggested link to Arm' })
  expect(
    Math.abs(parseFloat(cards[1].style.top) - parseFloat(cards[0].style.top))
  ).toBeGreaterThanOrEqual(250)
})

it('does not refetch suggestions while dragging or changing focus', async () => {
  const view = render(<GraphNavigator {...props} />)
  await screen.findByText('87% confidence')
  fireEvent.keyDown(screen.getByRole('button', { name: 'Move Arm' }), { key: 'ArrowRight' })
  view.rerender(<GraphNavigator {...props} focusedId="robot" />)
  await act(async () => {})
  expect(hardware.listHardwareSuggestions).toHaveBeenCalledTimes(1)
  expect(edges.listEdgeCandidates).toHaveBeenCalledTimes(1)
})

it('skips a candidate whose layout point is unavailable', () => {
  render(
    <GraphSuggestions projectId="p" visible={props.entities} points={{}} offset={{ x: 0, y: 0 }} />
  )
  expect(hardware.listHardwareSuggestions).not.toHaveBeenCalled()
  expect(edges.listEdgeCandidates).not.toHaveBeenCalled()
})

// --- edge candidates (SOLUSDEV-320): dashed cards anchored on the `to_entity_id` card ---

it('anchors an edge candidate on its target card with a sentence label and confirms it', async () => {
  vi.mocked(edges.listEdgeCandidates).mockResolvedValue([
    candidate,
    { ...candidate, id: 'elsewhere', to_entity_id: 'not-visible' }
  ])
  render(<GraphNavigator {...props} />)
  const card = await screen.findByRole('complementary', { name: 'Suggested commands to Servo 3' })
  expect(card.className).toContain('graph-suggestion--candidate')
  expect(card).toHaveTextContent('firmware.ino commands Servo 3 · 55%')
  expect(card).toHaveTextContent('fw.ino:3')
  expect(screen.getAllByRole('complementary')).toHaveLength(2) // hardware row + one candidate
  expect(parseFloat(card.style.left)).toBeGreaterThan(400)
  fireEvent.click(screen.getByRole('button', { name: 'Accept edge' }))
  await waitFor(() => expect(edges.confirmEdge).toHaveBeenCalledExactlyOnceWith('p', 'e1'))
  await waitFor(() => expect(screen.queryByText(/commands Servo 3/)).toBeNull())
  expect(props.onSuggestionsChanged).toHaveBeenCalled()
})

it('declines an edge candidate through the decline endpoint and keeps it on failure', async () => {
  vi.mocked(edges.listEdgeCandidates).mockResolvedValue([candidate])
  vi.mocked(edges.declineEdge).mockRejectedValueOnce(new Error('private response'))
  render(<GraphNavigator {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Decline edge' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save')
  expect(screen.getByText(/commands Servo 3/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Decline edge' }))
  await waitFor(() => expect(edges.declineEdge).toHaveBeenCalledTimes(2))
  expect(edges.declineEdge).toHaveBeenLastCalledWith('p', 'e1')
  await waitFor(() => expect(screen.queryByText(/commands Servo 3/)).toBeNull())
})

it('never asks for candidates on a level with no anchored cards', async () => {
  render(
    <GraphSuggestions projectId="p" visible={[]} points={props.positions} offset={{ x: 0, y: 0 }} />
  )
  await act(async () => {})
  expect(edges.listEdgeCandidates).not.toHaveBeenCalled()
})
