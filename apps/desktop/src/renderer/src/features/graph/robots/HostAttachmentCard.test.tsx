import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { HostAttachmentCard } from './HostAttachmentCard'
import { useProjectFolderStore } from '../../project/projectFolderStore'
import { useAuthStore } from '../../../store/authStore'
import { proposeHostTopology, confirmHostTopology } from '../../../lib/api/hostTopology'
import { ApiError } from '../../../lib/api/envelope.types'
const local = vi.hoisted(() => ({
  desktop: true,
  view: {
    source: { id: 'source', status: 'connected' },
    bridge: { connected: true },
    detected: [
      { entity_id: 'folder', entity_key: 'clone:', tool: 'root', name: 'Local controller folder' },
      { entity_id: 'python', entity_key: 'py:', tool: 'python', name: 'controller.py' },
      { entity_id: 'cad', entity_key: 'cad:', tool: 'kicad', name: 'Schematic' }
    ]
  },
  status: 'ready',
  machineAvailable: true,
  refresh: vi.fn()
}))
vi.mock('../../project/useLocalFolder', () => ({
  useLocalFolder: () => local,
  useMachineIdentity: () => ({ machine: { id: 'machine', name: 'Computer' } })
}))
vi.mock('../../../lib/desktopBridge', () => ({
  getDesktopFolderBridge: () =>
    local.desktop ? { machine: async () => ({ id: 'machine', name: 'Computer' }) } : null
}))
vi.mock('../../../lib/api/hostTopology', () => ({
  proposeHostTopology: vi.fn(),
  confirmHostTopology: vi.fn()
}))
vi.mock('../../project/ProjectFolderCard', () => ({
  ProjectFolderCard: () => <div>Existing native folder selector</div>
}))
const props = {
  projectId: 'project',
  endpointId: 'endpoint',
  robots: [{ id: 'robot', name: 'Robot' }],
  onConfirmed: vi.fn()
}
const topology = {
  robot_id: 'robot',
  nodes: [
    { id: 'host', name: 'Computer', role: 'brain' as const, brain_kind: 'host' as const },
    { id: 'endpoint', name: 'Controller', role: 'brain' as const }
  ],
  edges: [{ id: 'link', source: 'host', target: 'endpoint', protocol: 'usb' }],
  roots: ['host']
}
beforeEach(() => {
  vi.clearAllMocks()
  useAuthStore.setState({
    status: 'authenticated',
    accessToken: 'fixture-token',
    user: { email: 'fixture@example.invalid' }
  })
  useProjectFolderStore.setState({ folders: { project: { path: '/private/controller' } } })
  local.view.bridge.connected = true
  local.desktop = true
  local.view.source.id = 'source'
  vi.mocked(proposeHostTopology).mockResolvedValue({
    endpoint_id: 'endpoint',
    machine_id: 'machine',
    local_source_id: 'source',
    software_entity_id: 'python',
    host_name: 'Computer',
    proposal_digest: 'a'.repeat(64),
    topology,
    notes: ['No running process is verified.']
  })
  vi.mocked(confirmHostTopology).mockResolvedValue(topology)
})
async function review(): Promise<void> {
  fireEvent.click(screen.getByRole('button', { name: 'Connect this computer' }))
  expect((screen.getByLabelText('Local control software') as HTMLSelectElement).value).toBe('')
  fireEvent.change(screen.getByLabelText('Local control software'), { target: { value: 'python' } })
  fireEvent.click(screen.getByRole('button', { name: 'Review connection' }))
  await screen.findByRole('button', { name: 'Confirm graph connection' })
}
it('offers local choices with blank selection and reviews before separate confirmation', async () => {
  render(<HostAttachmentCard {...props} />)
  await review()
  expect(screen.queryByRole('option', { name: 'Schematic' })).toBeNull()
  expect(confirmHostTopology).not.toHaveBeenCalled()
  expect(proposeHostTopology).toHaveBeenCalledWith(
    'project',
    'robot',
    expect.objectContaining({ software_entity_id: 'python', local_source_id: 'source' }),
    expect.any(AbortSignal)
  )
  fireEvent.click(screen.getByRole('button', { name: 'Confirm graph connection' }))
  await screen.findByText('Computer connection saved.')
  expect(props.onConfirmed).toHaveBeenCalledOnce()
})

it.each(['project', 'endpoint', 'account', 'source'] as const)(
  'discards a pending review after %s changes',
  async (change) => {
    const proposal = await vi.mocked(proposeHostTopology)('project', 'robot', {
      endpoint_id: 'endpoint',
      machine_id: 'machine',
      local_source_id: 'source'
    })
    vi.mocked(proposeHostTopology).mockClear()
    let resolve!: (value: typeof proposal) => void
    vi.mocked(proposeHostTopology).mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done
        })
    )
    const mounted = render(<HostAttachmentCard {...props} />)
    fireEvent.click(screen.getByRole('button', { name: 'Connect this computer' }))
    fireEvent.change(screen.getByLabelText('Local control software'), {
      target: { value: 'python' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Review connection' }))
    const signal = vi.mocked(proposeHostTopology).mock.calls[0][3]!
    if (change === 'account')
      act(() => {
        const user = useAuthStore.getState().user
        useAuthStore.setState({ user: { email: 'other@example.invalid' } })
        useAuthStore.setState({ user })
      })
    else if (change === 'source') {
      local.view.source.id = 'replacement'
      mounted.rerender(<HostAttachmentCard {...props} />)
    } else
      mounted.rerender(
        <HostAttachmentCard
          {...props}
          {...(change === 'project' ? { projectId: 'other' } : { endpointId: 'other' })}
        />
      )
    await act(async () => resolve(proposal))
    expect(signal.aborted).toBe(true)
    expect(screen.queryByRole('button', { name: 'Confirm graph connection' })).toBeNull()
    expect(confirmHostTopology).not.toHaveBeenCalled()
  }
)

it('keeps a stable confirmation key on transport retry and blocks duplicate clicks', async () => {
  vi.mocked(confirmHostTopology).mockRejectedValueOnce(new Error('disconnected'))
  render(<HostAttachmentCard {...props} />)
  await review()
  const button = screen.getByRole('button', { name: 'Confirm graph connection' })
  fireEvent.click(button)
  fireEvent.click(button)
  await screen.findByRole('alert')
  expect(confirmHostTopology).toHaveBeenCalledTimes(1)
  fireEvent.click(button)
  await screen.findByText('Computer connection saved.')
  expect(vi.mocked(confirmHostTopology).mock.calls[0][3]).toBe(
    vi.mocked(confirmHostTopology).mock.calls[1][3]
  )
})

it('reuses the native folder selector when absent, and cannot review without desktop identity', () => {
  local.desktop = false
  useProjectFolderStore.setState({ folders: {} })
  render(<HostAttachmentCard {...props} />)
  fireEvent.click(screen.getByRole('button', { name: 'Connect this computer' }))
  expect(screen.getByText('Existing native folder selector')).toBeTruthy()
  expect(screen.getByText(/desktop companion is required/)).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Local control software'), { target: { value: 'python' } })
  fireEvent.click(screen.getByRole('button', { name: 'Review connection' }))
  expect(proposeHostTopology).not.toHaveBeenCalled()
})

it('sends an explicit MCU declaration and the selected shared robot only', async () => {
  render(
    <HostAttachmentCard
      {...props}
      robots={[...props.robots, { id: 'other', name: 'Other robot' }]}
    />
  )
  fireEvent.click(screen.getByRole('button', { name: 'Connect this computer' }))
  fireEvent.change(screen.getByLabelText('Robot for this connection'), {
    target: { value: 'other' }
  })
  fireEvent.change(screen.getByLabelText('Local control software'), { target: { value: 'folder' } })
  fireEvent.click(screen.getByLabelText('This endpoint is an MCU'))
  fireEvent.click(screen.getByRole('button', { name: 'Review connection' }))
  await screen.findByRole('button', { name: 'Confirm graph connection' })
  expect(proposeHostTopology).toHaveBeenCalledWith(
    'project',
    'other',
    {
      endpoint_id: 'endpoint',
      machine_id: 'machine',
      local_source_id: 'source',
      software_entity_id: 'folder',
      endpoint_brain_kind: 'mcu'
    },
    expect.any(AbortSignal)
  )
  expect(confirmHostTopology).not.toHaveBeenCalled()
})

it('expires a server-rejected stale review and requires new evidence', async () => {
  vi.mocked(confirmHostTopology).mockRejectedValueOnce(new ApiError(409, 'conflict', 'stale'))
  render(<HostAttachmentCard {...props} />)
  await review()
  fireEvent.click(screen.getByRole('button', { name: 'Confirm graph connection' }))
  await screen.findByText(
    'Connection evidence changed or is unavailable. Review the connection again.'
  )
  expect(screen.queryByRole('button', { name: 'Confirm graph connection' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Review connection' })).toBeTruthy()
})
it('cancel and a changed folder invalidate the review without applying it', async () => {
  const view = render(<HostAttachmentCard {...props} />)
  await review()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(confirmHostTopology).not.toHaveBeenCalled()
  await review()
  act(() => useProjectFolderStore.setState({ folders: { project: { path: '/private/other' } } }))
  view.rerender(<HostAttachmentCard {...props} />)
  expect(screen.queryByRole('button', { name: 'Confirm graph connection' })).toBeNull()
})
it('does not choose the first owner of a shared endpoint and refuses an offline companion', () => {
  local.view.bridge.connected = false
  render(
    <HostAttachmentCard
      {...props}
      robots={[...props.robots, { id: 'other', name: 'Other robot' }]}
    />
  )
  fireEvent.click(screen.getByRole('button', { name: 'Connect this computer' }))
  expect((screen.getByLabelText('Robot for this connection') as HTMLSelectElement).value).toBe('')
  expect(
    (screen.getByRole('button', { name: 'Review connection' }) as HTMLButtonElement).disabled
  ).toBe(true)
})

it('shows the mirror offer only after explicit local host confirmation', async () => {
  render(<HostAttachmentCard {...props} />)
  expect(screen.queryByRole('region', { name: 'Host telemetry mirror' })).toBeNull()
  await review()
  expect(screen.queryByText('Mirror existing control I/O')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Confirm graph connection' }))
  await screen.findByText('Mirror existing control I/O')
  expect(screen.getByLabelText('Control loop file')).toHaveValue('')
  expect(screen.getByLabelText('Method to observe')).toHaveValue('')
})
