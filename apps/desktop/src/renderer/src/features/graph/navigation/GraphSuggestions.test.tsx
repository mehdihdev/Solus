import { GraphSuggestions } from './GraphSuggestions'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { GraphNavigator, type GraphNavigatorProps } from './GraphNavigator'
import * as hardware from '../../../lib/api/hardware'
import { useAuthStore } from '../../../store/authStore'
vi.mock('../../../lib/api/hardware', () => ({
  listHardwareSuggestions: vi.fn(),
  acceptHardwareSuggestion: vi.fn(),
  rejectHardwareSuggestion: vi.fn()
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
const props: GraphNavigatorProps = {
  projectId: 'p',
  onSuggestionsChanged: vi.fn(),
  entities: [
    { id: 'robot', name: 'Arm', type: 'physical_robot', domain: 'project', source_key: null }
  ],
  relations: [],
  positions: { robot: { x: 0, y: 0 } },
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
})

it('skips a candidate whose layout point is unavailable', () => {
  render(
    <GraphSuggestions projectId="p" visible={props.entities} points={{}} offset={{ x: 0, y: 0 }} />
  )
  expect(hardware.listHardwareSuggestions).not.toHaveBeenCalled()
})
