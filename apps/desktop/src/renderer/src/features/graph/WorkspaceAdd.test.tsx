import { beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as resources from '../../lib/api/resources'
import { ApiError } from '../../lib/api/envelope.types'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useShellStore } from '../workspace/shellStore'
import { WorkspaceAdd } from './WorkspaceAdd'
import { clearServiceCatalog } from './useServiceCatalog'
vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources')>()),
  listConnections: vi.fn(),
  listAllSources: vi.fn(),
  listConnectionDocuments: vi.fn(),
  createSource: vi.fn(),
  addSourceDocument: vi.fn(),
  getJob: vi.fn(),
  triggerSync: vi.fn()
}))
const account: resources.Connection = {
  id: 'c1',
  provider: 'onshape',
  status: 'connected',
  account_login: 'builder',
  access: 'read',
  last_error: null,
  needs_reauth: null,
  health: 'healthy',
  projects: [],
  created_at: '',
  updated_at: ''
}
const source: resources.Source = {
  id: 's1',
  project_id: 'p1',
  type: 'onshape',
  name: 'CAD',
  status: 'connected',
  config: { documents: ['d1'] },
  connection_id: 'c1',
  account_login: 'builder',
  last_error: null,
  last_synced_at: 't',
  created_at: '',
  updated_at: ''
}
const selected = vi.fn()
beforeEach(() => {
  vi.clearAllMocks()
  clearServiceCatalog()
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover' } })
  vi.mocked(resources.listConnections).mockResolvedValue([account])
  vi.mocked(resources.listAllSources).mockResolvedValue([source])
  vi.mocked(resources.listConnectionDocuments).mockResolvedValue({
    items: [
      { id: 'd1', name: 'Arm' },
      { id: 'd2', name: 'Gripper' }
    ],
    cached: true,
    fetched_at: 'now'
  })
})
it('keeps the account dropdown mounted through close/reopen with zero extra reads', async () => {
  render(<WorkspaceAdd projectId="p1" onSelected={selected} />)
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  expect(screen.getByRole('dialog', { name: 'Add to graph' })).toBeInTheDocument()
  expect(screen.queryByRole('tab', { name: 'From a service' })).toBeNull()
  expect(screen.queryByRole('tab', { name: 'Integrations' })).toBeNull()
  // The first usable account is selected on open; its rows carry the In graph pill.
  expect(await screen.findByRole('tab', { name: 'onshape · builder' })).toHaveAttribute(
    'aria-selected',
    'true'
  )
  expect(await screen.findByRole('button', { name: 'Arm · In graph' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Close Add' }))
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  expect(screen.getByRole('button', { name: 'Arm · In graph' })).toBeInTheDocument()
  expect(resources.listConnections).toHaveBeenCalledTimes(1)
  expect(resources.listAllSources).toHaveBeenCalledTimes(1)
  expect(resources.listConnectionDocuments).toHaveBeenCalledTimes(1)
})
it('reselects an existing document without any mutation or job request', async () => {
  render(<WorkspaceAdd projectId="p1" onSelected={selected} />)
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Arm · In graph' }))
  expect(selected).toHaveBeenCalledWith({ source, jobId: null }, 'd1')
  expect(resources.createSource).not.toHaveBeenCalled()
  expect(resources.addSourceDocument).not.toHaveBeenCalled()
  expect(resources.getJob).not.toHaveBeenCalled()
})
it('adds the second document once and updates the graph after its accepted job', async () => {
  vi.mocked(resources.addSourceDocument).mockResolvedValue({
    job_id: 'j1',
    status: 'queued',
    source: { ...source, config: { documents: ['d1', 'd2'] } }
  })
  vi.mocked(resources.getJob).mockResolvedValue({
    id: 'j1',
    project_id: 'p1',
    status: 'succeeded',
    error: null
  })
  render(<WorkspaceAdd projectId="p1" onSelected={selected} />)
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  expect(screen.getByRole('button', { name: 'Select documents' })).toBeDisabled()
  await userEvent.click(await screen.findByRole('button', { name: 'Gripper' }))
  expect(screen.getByRole('button', { name: 'Gripper' })).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'Add 1 document' }))
  await waitFor(() => expect(selected).toHaveBeenCalledTimes(1))
  expect(resources.addSourceDocument).toHaveBeenCalledTimes(1)
  expect(resources.addSourceDocument).toHaveBeenCalledWith('p1', 's1', 'd2', expect.anything())
  expect(resources.triggerSync).not.toHaveBeenCalled()
  // Confirmed picks toast and close the modal.
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(useShellStore.getState().toast?.title).toBe('Added 1 document from builder')
})

it.each(['project', 'account'])(
  'never revives a pending import after leaving and returning to the same %s',
  async (boundary) => {
    vi.mocked(resources.listAllSources).mockResolvedValue([])
    let resolve: (source: resources.Source) => void = () => undefined
    vi.mocked(resources.createSource).mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done
        })
    )
    render(<WorkspaceAdd projectId="p1" onSelected={selected} />)
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Arm' }))
    await userEvent.click(screen.getByRole('button', { name: 'Add 1 document' }))
    await waitFor(() => expect(resources.createSource).toHaveBeenCalledOnce())
    act(() => {
      if (boundary === 'project') {
        useWorkspaceStore.setState({ project: { id: 'p2', name: 'Other' } })
        useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover' } })
      } else {
        const previous = useAuthStore.getState()
        useAuthStore.setState({ status: 'unauthenticated' })
        useAuthStore.setState({ status: previous.status })
      }
    })
    await act(async () => {
      resolve({ ...source, config: { documents: [] } })
    })
    expect(resources.addSourceDocument).not.toHaveBeenCalled()
    expect(resources.triggerSync).not.toHaveBeenCalled()
    expect(selected).not.toHaveBeenCalled()
  }
)

it('requires explicit loading for an uncached listing and shows job failures without retrying sync', async () => {
  vi.mocked(resources.listConnectionDocuments).mockRejectedValueOnce(
    new ApiError(409, 'listing_not_cached', 'Not cached')
  )
  render(<WorkspaceAdd projectId="p1" onSelected={selected} />)
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  const load = await screen.findByRole('button', { name: 'Load documents' })
  expect(resources.listConnectionDocuments).toHaveBeenCalledTimes(1)
  await userEvent.click(load)
  expect(resources.listConnectionDocuments).toHaveBeenLastCalledWith(
    'c1',
    { refresh: true },
    expect.anything()
  )
  vi.mocked(resources.addSourceDocument).mockResolvedValue({
    job_id: 'j1',
    status: 'queued',
    source: { ...source, config: { documents: ['d1', 'd2'] } }
  })
  vi.mocked(resources.getJob).mockResolvedValue({
    id: 'j1',
    project_id: 'p1',
    status: 'failed',
    error: { message: 'Export unavailable' }
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Gripper' }))
  await userEvent.click(screen.getByRole('button', { name: 'Add 1 document' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Export unavailable')
  // A failed import stays open and visible; re-selecting the now-attached row repeats it.
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Gripper · In graph' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Export unavailable')
  expect(resources.addSourceDocument).toHaveBeenCalledOnce()
  expect(resources.triggerSync).not.toHaveBeenCalled()
  expect(selected).not.toHaveBeenCalled()
})

it('opens on the requested tab when a sequence-keyed request arrives', async () => {
  const view = render(<WorkspaceAdd projectId="p1" onSelected={selected} hardware={<p>HW</p>} />)
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  view.rerender(
    <WorkspaceAdd
      projectId="p1"
      onSelected={selected}
      hardware={<p>HW</p>}
      openRequest={{ tab: 'hardware', sequence: 1 }}
    />
  )
  expect(await screen.findByRole('tab', { name: 'Hardware', selected: true })).toBeInTheDocument()
  expect(screen.getByText('HW')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Close Add' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  // The same request again is not a new request.
  view.rerender(
    <WorkspaceAdd
      projectId="p1"
      onSelected={selected}
      hardware={<p>HW</p>}
      openRequest={{ tab: 'hardware', sequence: 1 }}
    />
  )
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('the .solus row offers the dropzone and Choose files, both through the import handler', async () => {
  const choose = vi.fn()
  const importFiles = vi.fn().mockResolvedValue(undefined)
  render(
    <WorkspaceAdd
      projectId="p1"
      onSelected={selected}
      solusUpload={{ target: 'Documentation', choose, importFiles }}
    />
  )
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  await userEvent.click(screen.getByRole('tab', { name: '.solus' }))
  expect(screen.getByText('.solus › Documentation')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Choose files' }))
  expect(choose).toHaveBeenCalledOnce()
  const file = new File(['x'], 'notes.md', { type: 'text/markdown' })
  fireEvent.drop(screen.getByRole('button', { name: 'Upload documents' }), {
    dataTransfer: { files: [file] }
  })
  expect(importFiles).toHaveBeenCalledWith([file])
})

it('closes on the backdrop and opens on the first account for a service request', async () => {
  const view = render(<WorkspaceAdd projectId="p1" onSelected={selected} />)
  view.rerender(
    <WorkspaceAdd
      projectId="p1"
      onSelected={selected}
      openRequest={{ tab: 'service', sequence: 1 }}
    />
  )
  expect(
    await screen.findByRole('tab', { name: 'onshape · builder', selected: true })
  ).toBeInTheDocument()
  fireEvent.click(document.querySelector('.modal-backdrop-in')!)
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
