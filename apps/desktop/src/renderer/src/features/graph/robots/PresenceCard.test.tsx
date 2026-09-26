import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { listPresenceProfiles, preparePresence, type PresencePlan } from '../../../lib/api/presence'
import { sendMessage } from '../../sol/solChatStore'
import { PresenceCard } from './PresenceCard'
const open = vi.hoisted(() => vi.fn())
vi.mock('../../../lib/api/presence', () => ({
  listPresenceProfiles: vi.fn(),
  preparePresence: vi.fn()
}))
vi.mock('../../sol/solChatStore', () => ({ sendMessage: vi.fn() }))
vi.mock('../../../lib/desktopBridge', () => ({ getDesktopSolBridge: () => ({ open }) }))
const props = { projectId: 'p', brainId: 'b', robots: [{ id: 'r', name: 'Board' }] }
const plan: PresencePlan = {
  plan_id: '00000000-0000-0000-0000-000000000001',
  source: 'complete fixture source',
  source_sha256: 'a'.repeat(64),
  binary_sha256: 'b'.repeat(64),
  profile: 'uno_avr',
  status: 'prepared',
  target: {
    binding: 'port-1',
    path: '/dev/ttyUSB0',
    vid: 6790,
    pid: 29987,
    serial: null,
    location: '1',
    manual_confirmation_required: true
  }
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listPresenceProfiles).mockResolvedValue([
    { id: 'uno_avr', label: 'Arduino Uno', available: true, reason: null }
  ])
  vi.mocked(preparePresence).mockResolvedValue(plan)
  vi.mocked(sendMessage).mockResolvedValue(true)
})
async function choose(): Promise<void> {
  await screen.findByRole('option', { name: 'Arduino Uno' })
  fireEvent.change(screen.getByLabelText('Board profile'), { target: { value: 'uno_avr' } })
  fireEvent.change(screen.getByRole('combobox', { name: 'Presence firmware' }), {
    target: { value: 'heartbeat' }
  })
}
it('requires choices and reviews full source before requesting the existing gate, never approving', async () => {
  render(<PresenceCard {...props} />)
  expect(screen.getByRole('button', { name: 'Prepare firmware' })).toBeDisabled()
  await choose()
  fireEvent.click(screen.getByText('Prepare firmware'))
  await screen.findByText(plan.source)
  expect(sendMessage).not.toHaveBeenCalled()
  expect(screen.getByText(/Existing firmware will be erased/)).toBeInTheDocument()
  fireEvent.click(screen.getByText('Request flash review'))
  await screen.findByText(/Review requested/)
  expect(sendMessage).toHaveBeenCalledWith('p', expect.stringContaining(plan.plan_id), 'do')
  expect(sendMessage).toHaveBeenCalledOnce()
  expect(open).toHaveBeenCalledOnce()
  expect(screen.getByText('Request flash review')).toBeDisabled()
})
it('discards late preparation across profile A to empty to A', async () => {
  let resolve!: (value: PresencePlan) => void
  vi.mocked(preparePresence).mockReturnValue(
    new Promise((r) => {
      resolve = r
    })
  )
  render(<PresenceCard {...props} />)
  await choose()
  fireEvent.click(screen.getByText('Prepare firmware'))
  fireEvent.change(screen.getByLabelText('Board profile'), { target: { value: '' } })
  fireEvent.change(screen.getByLabelText('Board profile'), { target: { value: 'uno_avr' } })
  await act(async () => resolve(plan))
  expect(screen.queryByText(plan.source)).not.toBeInTheDocument()
})
it('discards late preparation across project A to B to A', async () => {
  let resolve!: (value: PresencePlan) => void
  vi.mocked(preparePresence).mockReturnValue(
    new Promise((r) => {
      resolve = r
    })
  )
  const view = render(<PresenceCard {...props} />)
  await choose()
  fireEvent.click(screen.getByText('Prepare firmware'))
  view.rerender(<PresenceCard {...props} projectId="other" />)
  view.rerender(<PresenceCard {...props} />)
  await act(async () => resolve(plan))
  expect(screen.queryByText(plan.source)).not.toBeInTheDocument()
})
it('shows unavailable profiles and requires an explicit robot when several exist', async () => {
  vi.mocked(listPresenceProfiles).mockResolvedValue([
    { id: 'uno_avr', label: 'Arduino Uno', available: false, reason: 'Compiler unavailable' }
  ])
  render(<PresenceCard {...props} robots={[...props.robots, { id: 'r2', name: 'Other' }]} />)
  await screen.findByText('Compiler unavailable')
  expect(screen.getByLabelText('Presence robot')).toHaveValue('')
  expect(screen.getByRole('button', { name: 'Prepare firmware' })).toBeDisabled()
})

it('does not report review success when the existing chat refuses the turn', async () => {
  vi.mocked(sendMessage).mockResolvedValue(false)
  render(<PresenceCard {...props} />)
  await choose()
  fireEvent.click(screen.getByText('Prepare firmware'))
  await screen.findByText(plan.source)
  fireEvent.click(screen.getByText('Request flash review'))
  await screen.findByRole('alert')
  expect(screen.queryByText(/Review requested/)).not.toBeInTheDocument()
})
it('reports preparation failure without exposing internal errors or offering a flash', async () => {
  vi.mocked(preparePresence).mockRejectedValue(new Error('private path'))
  render(<PresenceCard {...props} />)
  await choose()
  fireEvent.click(screen.getByText('Prepare firmware'))
  await screen.findByRole('alert')
  expect(screen.queryByText('private path')).not.toBeInTheDocument()
  expect(screen.queryByText('Request flash review')).not.toBeInTheDocument()
})
it('reports missing provider and profile lookup errors honestly', async () => {
  vi.mocked(listPresenceProfiles).mockResolvedValue([])
  const view = render(<PresenceCard {...props} />)
  await screen.findByText('Local firmware provider unavailable.')
  vi.mocked(listPresenceProfiles).mockRejectedValue(new Error('secret'))
  view.rerender(<PresenceCard {...props} brainId="other" />)
  await screen.findByRole('alert')
  expect(screen.queryByText('secret')).not.toBeInTheDocument()
})
it('explains probe limits and invalidates a prepared plan on kind and robot changes', async () => {
  render(<PresenceCard {...props} robots={[...props.robots, { id: 'second', name: 'Second' }]} />)
  await choose()
  fireEvent.change(screen.getByLabelText('Presence robot'), { target: { value: 'r' } })
  fireEvent.change(screen.getByRole('combobox', { name: 'Presence firmware' }), {
    target: { value: 'probe' }
  })
  expect(screen.getByText(/Analog readings are raw/)).toBeInTheDocument()
  fireEvent.click(screen.getByText('Prepare firmware'))
  await screen.findByText(plan.source)
  fireEvent.change(screen.getByLabelText('Presence robot'), { target: { value: 'second' } })
  expect(screen.queryByText(plan.source)).not.toBeInTheDocument()
})

it('keeps topology preparation disabled without accepted wiring', async () => {
  render(<PresenceCard {...props} />)
  await choose()
  fireEvent.change(screen.getByRole('combobox', { name: 'Presence firmware' }), {
    target: { value: 'topology' }
  })
  expect(screen.getByRole('button', { name: 'Prepare firmware' })).toBeDisabled()
  expect(preparePresence).not.toHaveBeenCalled()
})

vi.mock('../../../lib/api/presenceWiring', () => ({
  proposeWiring: vi.fn(),
  acceptWiring: vi.fn()
}))
it('uses only accepted wiring to prepare input firmware and invalidates it on edit', async () => {
  const { proposeWiring, acceptWiring } = await import('../../../lib/api/presenceWiring')
  const wiring = {
    proposal_id: plan.plan_id,
    digest: 'a'.repeat(64),
    profile_id: 'uno_avr' as const,
    mode: 'typed' as const,
    wiring: [],
    observations: [],
    unresolved: [],
    status: 'proposed' as const
  }
  vi.mocked(proposeWiring).mockResolvedValue(wiring)
  vi.mocked(acceptWiring).mockResolvedValue({
    proposal_id: plan.plan_id,
    digest: wiring.digest,
    status: 'accepted'
  })
  render(<PresenceCard {...props} />)
  await choose()
  fireEvent.click(screen.getByText('Tell me'))
  fireEvent.click(screen.getByText('Review wiring'))
  await screen.findByText('Accept wiring')
  fireEvent.click(screen.getByText('Accept wiring'))
  await screen.findByText('Wiring accepted for firmware preparation.')
  fireEvent.change(screen.getByRole('combobox', { name: 'Presence firmware' }), {
    target: { value: 'topology' }
  })
  fireEvent.click(screen.getByText('Prepare firmware'))
  await screen.findByText(plan.source)
  expect(preparePresence).toHaveBeenLastCalledWith('p', 'r', 'b', {
    profile_id: 'uno_avr',
    kind: 'topology',
    channel: 'uno.alive',
    wiring_proposal_id: plan.plan_id
  })
  fireEvent.change(screen.getByLabelText('Channel 1'), { target: { value: 'light' } })
  expect(screen.queryByText(plan.source)).not.toBeInTheDocument()
  expect(screen.getByText('Prepare firmware')).toBeDisabled()
})
