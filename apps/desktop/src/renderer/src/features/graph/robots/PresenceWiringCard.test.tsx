import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { proposeWiring, acceptWiring } from '../../../lib/api/presenceWiring'
import { listAllSources } from '../../../lib/api/resources'
import { listRuns } from '../../bench/runs/runsApi'
import { PresenceWiringCard } from './PresenceWiringCard'
vi.mock('../../../lib/api/presenceWiring', () => ({
  proposeWiring: vi.fn(),
  acceptWiring: vi.fn()
}))
vi.mock('../../../lib/api/resources', () => ({ listAllSources: vi.fn() }))
vi.mock('../../bench/runs/runsApi', () => ({ listRuns: vi.fn() }))
const proposal = {
  proposal_id: '00000000-0000-0000-0000-000000000001',
  digest: 'a'.repeat(64),
  profile_id: 'uno_avr' as const,
  mode: 'typed' as const,
  wiring: [{ channel: 'light', pin: 'A0', kind: 'analog_input' as const }],
  observations: [{ detail: 'Declared, not observed', confidence: null }],
  unresolved: ['I2C identity unknown'],
  status: 'proposed' as const
}
const props = {
  projectId: 'p',
  robotId: 'r',
  brainId: 'b',
  profileId: 'uno_avr' as const,
  onAccepted: vi.fn()
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(proposeWiring).mockResolvedValue(proposal)
  vi.mocked(acceptWiring).mockResolvedValue({ ...proposal, status: 'accepted' })
  vi.mocked(listAllSources).mockResolvedValue([])
  vi.mocked(listRuns).mockResolvedValue({ runs: [], next_cursor: null })
})
function typed(): void {
  fireEvent.click(screen.getByRole('button', { name: 'Tell me' }))
  fireEvent.change(screen.getByLabelText('Channel 1'), { target: { value: 'light' } })
  fireEvent.change(screen.getByLabelText('Pin 1'), { target: { value: 'A0' } })
}
it('reviews typed evidence before explicit acceptance, never prepares or flashes', async () => {
  render(<PresenceWiringCard {...props} />)
  typed()
  fireEvent.click(screen.getByText('Review wiring'))
  await screen.findByText('Declared, not observed')
  expect(props.onAccepted).not.toHaveBeenCalledWith(proposal.proposal_id)
  expect(screen.getByText('I2C identity unknown')).toBeVisible()
  fireEvent.click(screen.getByText('Accept wiring'))
  await screen.findByText('Wiring accepted for firmware preparation.')
  expect(props.onAccepted).toHaveBeenLastCalledWith(proposal.proposal_id)
})
it('invalidates late proposal across choices', async () => {
  let done!: (v: typeof proposal) => void
  vi.mocked(proposeWiring).mockReturnValue(
    new Promise((r) => {
      done = r
    })
  )
  render(<PresenceWiringCard {...props} />)
  typed()
  fireEvent.click(screen.getByText('Review wiring'))
  fireEvent.click(screen.getByText('From the schematic'))
  await act(async () => done(proposal))
  expect(screen.queryByText('Declared, not observed')).not.toBeInTheDocument()
})
it('explains actual probe prerequisite and no captured runs honestly', async () => {
  render(<PresenceWiringCard {...props} />)
  fireEvent.click(screen.getByText('Let me look'))
  await screen.findByText(/No completed runs available/)
  expect(screen.getByText(/First prepare the probe/)).toBeVisible()
  expect(screen.getByText('Review wiring')).toBeDisabled()
})
it('discards accepted proposal on project changes', async () => {
  const v = render(<PresenceWiringCard {...props} />)
  typed()
  fireEvent.click(screen.getByText('Review wiring'))
  await screen.findByText('Declared, not observed')
  v.rerender(<PresenceWiringCard {...props} projectId="q" />)
  expect(screen.queryByText('Accept wiring')).not.toBeInTheDocument()
})

it('selects only connected electrical sources and preserves explicit declarations', async () => {
  vi.mocked(listAllSources).mockResolvedValue([
    { id: 'electrical', name: 'Board schematic', type: 'kicad', status: 'connected' },
    { id: 'remote', name: 'Remote code', type: 'github', status: 'connected' },
    { id: 'offline', name: 'Offline board', type: 'altium', status: 'disconnected' }
  ] as Awaited<ReturnType<typeof listAllSources>>)
  vi.mocked(proposeWiring).mockResolvedValue({ ...proposal, mode: 'schematic' })
  render(<PresenceWiringCard {...props} />)
  fireEvent.click(screen.getByText('From the schematic'))
  await screen.findByText('Board schematic')
  expect(screen.queryByText('Remote code')).not.toBeInTheDocument()
  expect(screen.queryByText('Offline board')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Electrical source'), { target: { value: 'electrical' } })
  fireEvent.change(screen.getByLabelText('Channel 1'), { target: { value: 'switch' } })
  fireEvent.change(screen.getByLabelText('Pin 1'), { target: { value: 'D2' } })
  fireEvent.change(screen.getByLabelText('Input kind 1'), { target: { value: 'digital_input' } })
  fireEvent.click(screen.getByText('Review wiring'))
  await screen.findByText('Declared, not observed')
  expect(proposeWiring).toHaveBeenLastCalledWith('p', 'r', 'b', {
    profile_id: 'uno_avr',
    mode: 'schematic',
    source_id: 'electrical',
    wiring: [{ channel: 'switch', pin: 'D2', kind: 'digital_input' }]
  })
})
it('discloses lookup failure and retries choices without accepting stale data', async () => {
  vi.mocked(listAllSources).mockRejectedValueOnce(new Error('private path'))
  render(<PresenceWiringCard {...props} />)
  fireEvent.click(screen.getByText('From the schematic'))
  await screen.findByRole('alert')
  expect(screen.queryByText('private path')).not.toBeInTheDocument()
  fireEvent.click(screen.getByText('From the schematic'))
  await screen.findByText('No connected electrical sources available.')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
it('allows same-proposal retry after failed acceptance and editing invalidates it', async () => {
  vi.mocked(acceptWiring).mockRejectedValueOnce(new Error('private'))
  render(<PresenceWiringCard {...props} />)
  typed()
  fireEvent.click(screen.getByText('Review wiring'))
  await screen.findByText('Declared, not observed')
  fireEvent.click(screen.getByText('Accept wiring'))
  await screen.findByRole('alert')
  expect(props.onAccepted).not.toHaveBeenCalledWith(proposal.proposal_id)
  fireEvent.click(screen.getByText('Accept wiring'))
  await screen.findByText('Wiring accepted for firmware preparation.')
  fireEvent.change(screen.getByLabelText('Pin 1'), { target: { value: 'A1' } })
  expect(props.onAccepted).toHaveBeenLastCalledWith(null)
  expect(screen.queryByText('Accept wiring')).not.toBeInTheDocument()
})
it('discards late acceptance after account generation changes', async () => {
  let done!: (v: Awaited<ReturnType<typeof acceptWiring>>) => void
  vi.mocked(acceptWiring).mockReturnValue(
    new Promise((r) => {
      done = r
    })
  )
  const view = render(<PresenceWiringCard {...props} />)
  typed()
  fireEvent.click(screen.getByText('Review wiring'))
  await screen.findByText('Declared, not observed')
  fireEvent.click(screen.getByText('Accept wiring'))
  view.rerender(<PresenceWiringCard {...props} projectId="q" />)
  await act(async () =>
    done({ proposal_id: proposal.proposal_id, digest: proposal.digest, status: 'accepted' })
  )
  expect(props.onAccepted).not.toHaveBeenCalledWith(proposal.proposal_id)
})
it('renders recorded run provenance and does not infer wiring from it', async () => {
  vi.mocked(listRuns).mockResolvedValue({
    runs: [
      { id: 'run', robot_id: 'r', name: 'Probe baseline', status: 'completed', origin: 'recorded' }
    ] as Awaited<ReturnType<typeof listRuns>>['runs'],
    next_cursor: null
  })
  vi.mocked(proposeWiring).mockResolvedValue({ ...proposal, mode: 'probe', wiring: [] })
  render(<PresenceWiringCard {...props} />)
  fireEvent.click(screen.getByText('Let me look'))
  await screen.findByText('Probe baseline (recorded)')
  fireEvent.change(screen.getByLabelText('Captured probe run'), { target: { value: 'run' } })
  fireEvent.click(screen.getByText('Review wiring'))
  await screen.findByText('No input channels declared.')
  expect(proposeWiring).toHaveBeenLastCalledWith('p', 'r', 'b', {
    profile_id: 'uno_avr',
    mode: 'probe',
    run_id: 'run',
    wiring: []
  })
})
it('rejects invalid explicit pins, supports removing rows, and handles review failure', async () => {
  vi.mocked(proposeWiring).mockRejectedValueOnce(new Error('private'))
  render(<PresenceWiringCard {...props} />)
  typed()
  fireEvent.change(screen.getByLabelText('Pin 1'), { target: { value: '2' } })
  expect(screen.getByText('Review wiring')).toBeDisabled()
  fireEvent.click(screen.getByText('Add input'))
  fireEvent.click(screen.getByText('Remove input 1'))
  fireEvent.click(screen.getByText('Review wiring'))
  await screen.findByRole('alert')
  expect(screen.queryByText('private')).not.toBeInTheDocument()
  expect(screen.queryByText('Accept wiring')).not.toBeInTheDocument()
})
it('accepts 64-character declared channels but disables review at 65 characters', async () => {
  render(<PresenceWiringCard {...props} />)
  typed()
  const channel = screen.getByLabelText('Channel 1')
  fireEvent.change(channel, { target: { value: 'a'.repeat(64) } })
  expect(screen.getByText('Review wiring')).toBeEnabled()
  fireEvent.change(channel, { target: { value: 'a'.repeat(65) } })
  expect(screen.getByText('Review wiring')).toBeDisabled()
  expect(channel).toHaveAttribute('maxlength', '64')
  await act(async () => {})
})
it('loads an eligible older probe on explicit page two and preserves its selection', async () => {
  const run = {
    id: 'older',
    robot_id: 'r',
    name: 'Older probe',
    status: 'completed',
    origin: 'recorded'
  } as Awaited<ReturnType<typeof listRuns>>['runs'][number]
  vi.mocked(listRuns)
    .mockResolvedValueOnce({ runs: [], next_cursor: 'page2' })
    .mockResolvedValueOnce({ runs: [run], next_cursor: 'page3' })
    .mockResolvedValueOnce({ runs: [], next_cursor: null })
  render(<PresenceWiringCard {...props} />)
  fireEvent.click(screen.getByText('Let me look'))
  fireEvent.click(await screen.findByText('Load more recorded runs'))
  await screen.findByText('Older probe (recorded)')
  expect(listRuns).toHaveBeenNthCalledWith(2, 'p', 'page2', expect.any(AbortSignal))
  fireEvent.change(screen.getByLabelText('Captured probe run'), { target: { value: 'older' } })
  fireEvent.click(screen.getByText('Load more recorded runs'))
  await act(async () => {})
  expect(screen.getByLabelText('Captured probe run')).toHaveValue('older')
  expect(screen.queryByText('Load more recorded runs')).not.toBeInTheDocument()
})
it('aborts and ignores page two when switching evidence modes', async () => {
  let done!: (page: Awaited<ReturnType<typeof listRuns>>) => void
  vi.mocked(listRuns)
    .mockResolvedValueOnce({ runs: [], next_cursor: 'page2' })
    .mockReturnValueOnce(
      new Promise((r) => {
        done = r
      })
    )
  render(<PresenceWiringCard {...props} />)
  fireEvent.click(screen.getByText('Let me look'))
  fireEvent.click(await screen.findByText('Load more recorded runs'))
  fireEvent.click(screen.getByText('From the schematic'))
  expect(vi.mocked(listRuns).mock.calls[1][2]?.aborted).toBe(true)
  await act(async () =>
    done({
      runs: [
        { id: 'older', robot_id: 'r', name: 'Late probe', status: 'completed', origin: 'recorded' }
      ] as Awaited<ReturnType<typeof listRuns>>['runs'],
      next_cursor: 'page3'
    })
  )
  expect(screen.queryByText('Late probe (recorded)')).not.toBeInTheDocument()
  expect(screen.queryByText('Load more recorded runs')).not.toBeInTheDocument()
})
it('stops pagination at a repeated cursor instead of permitting a loop', async () => {
  vi.mocked(listRuns)
    .mockResolvedValueOnce({ runs: [], next_cursor: 'page2' })
    .mockResolvedValueOnce({ runs: [], next_cursor: 'page2' })
  render(<PresenceWiringCard {...props} />)
  fireEvent.click(screen.getByText('Let me look'))
  fireEvent.click(await screen.findByText('Load more recorded runs'))
  await screen.findByRole('alert')
  expect(screen.queryByText('Load more recorded runs')).not.toBeInTheDocument()
  expect(listRuns).toHaveBeenCalledTimes(2)
})
