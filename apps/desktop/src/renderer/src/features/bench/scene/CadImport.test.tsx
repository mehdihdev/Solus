import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { CadImport } from './CadImport'
import { cadSources, startCadImport, cadImportStatus } from './cadApi'

vi.mock('./cadApi', () => ({
  cadSources: vi.fn(),
  startCadImport: vi.fn(),
  cadImportStatus: vi.fn()
}))
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(cadSources).mockResolvedValue([
    { id: 'source', name: 'Follower assembly', observed_microversion: 'revision' }
  ])
  vi.mocked(startCadImport).mockResolvedValue({
    import_id: 'import',
    status: 'pending',
    reason: null,
    job_id: 'job',
    model_id: null
  })
  vi.mocked(cadImportStatus).mockResolvedValue({
    import_id: 'import',
    status: 'complete',
    reason: null,
    job_id: 'job',
    model_id: 'model'
  })
})

it('imports only an explicitly chosen revision and refreshes models after completion', async () => {
  const onImported = vi.fn()
  render(<CadImport projectId="project" robotId="robot" onImported={onImported} />)
  fireEvent.change(await screen.findByLabelText('Connected CAD source'), {
    target: { value: 'source' }
  })
  expect(startCadImport).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Import connected CAD' }))
  await waitFor(() =>
    expect(startCadImport).toHaveBeenCalledWith(
      'project',
      {
        robot_id: 'robot',
        source_entity_id: 'source',
        expected_revision: 'revision'
      },
      expect.any(AbortSignal)
    )
  )
  expect(await screen.findByText('CAD model imported.')).toBeInTheDocument()
  expect(onImported).toHaveBeenCalledOnce()
  expect(cadSources).toHaveBeenCalledWith('project', expect.any(AbortSignal), true)
})

it('requires a robot and a known source revision', async () => {
  vi.mocked(cadSources).mockResolvedValue([
    { id: 'source', name: 'Unsynced assembly', observed_microversion: null }
  ])
  render(<CadImport projectId="project" robotId="" onImported={vi.fn()} />)
  expect(await screen.findByRole('option', { name: /Unsynced assembly/ })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Import connected CAD' })).toBeDisabled()
})

it('aborts stale import status and never refreshes another robot', async () => {
  let resolve!: (value: Awaited<ReturnType<typeof startCadImport>>) => void
  vi.mocked(startCadImport).mockReturnValue(
    new Promise((done) => {
      resolve = done
    })
  )
  const onImported = vi.fn()
  const view = render(<CadImport projectId="project" robotId="robot" onImported={onImported} />)
  fireEvent.change(await screen.findByLabelText('Connected CAD source'), {
    target: { value: 'source' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Import connected CAD' }))
  view.rerender(<CadImport projectId="project" robotId="other" onImported={onImported} />)
  await act(async () =>
    resolve({
      import_id: 'import',
      status: 'complete',
      reason: null,
      job_id: null,
      model_id: 'model'
    })
  )
  expect(onImported).not.toHaveBeenCalled()
  expect(vi.mocked(startCadImport).mock.calls[0][2]?.aborted).toBe(true)
})

it('offers status retry without repeating the import mutation', async () => {
  vi.mocked(cadImportStatus).mockRejectedValueOnce(new Error('offline'))
  render(<CadImport projectId="project" robotId="robot" onImported={vi.fn()} />)
  fireEvent.change(await screen.findByLabelText('Connected CAD source'), {
    target: { value: 'source' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Import connected CAD' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Check import status' }))
  expect(await screen.findByText('CAD model imported.')).toBeInTheDocument()
  expect(startCadImport).toHaveBeenCalledOnce()
})

it('ignores a completed poll after unmount and aborts its request', async () => {
  let resolve!: (value: Awaited<ReturnType<typeof cadImportStatus>>) => void
  vi.mocked(cadImportStatus).mockReturnValue(
    new Promise((done) => {
      resolve = done
    })
  )
  const onImported = vi.fn()
  const view = render(<CadImport projectId="project" robotId="robot" onImported={onImported} />)
  fireEvent.change(await screen.findByLabelText('Connected CAD source'), {
    target: { value: 'source' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Import connected CAD' }))
  await waitFor(() => expect(cadImportStatus).toHaveBeenCalledOnce())
  view.unmount()
  await act(async () =>
    resolve({
      import_id: 'import',
      status: 'complete',
      reason: null,
      job_id: null,
      model_id: 'model'
    })
  )
  expect(onImported).not.toHaveBeenCalled()
  expect(vi.mocked(cadImportStatus).mock.calls[0][2]?.aborted).toBe(true)
})

it('shows truthful source and import failures', async () => {
  vi.mocked(cadImportStatus).mockResolvedValue({
    import_id: 'import',
    status: 'error',
    reason: 'Geometry unavailable',
    job_id: null,
    model_id: null
  })
  render(<CadImport projectId="project" robotId="robot" onImported={vi.fn()} />)
  fireEvent.change(await screen.findByLabelText('Connected CAD source'), {
    target: { value: 'source' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Import connected CAD' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Geometry unavailable')
})

it('polls a pending job without starting another import', async () => {
  vi.mocked(cadImportStatus).mockResolvedValueOnce({
    import_id: 'import',
    status: 'pending',
    reason: null,
    job_id: 'job',
    model_id: null
  })
  render(<CadImport projectId="project" robotId="robot" onImported={vi.fn()} />)
  fireEvent.change(await screen.findByLabelText('Connected CAD source'), {
    target: { value: 'source' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Import connected CAD' }))
  expect(await screen.findByText('CAD model imported.', {}, { timeout: 2500 })).toBeInTheDocument()
  expect(cadImportStatus).toHaveBeenCalledTimes(2)
  expect(startCadImport).toHaveBeenCalledOnce()
})

it('shows an honest empty state', async () => {
  vi.mocked(cadSources).mockResolvedValue([])
  render(<CadImport projectId="project" robotId="robot" onImported={vi.fn()} />)
  expect(await screen.findByText(/No synced CAD sources yet/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Import connected CAD' })).toBeDisabled()
})

it('shows source acquisition errors without proposing an import', async () => {
  vi.mocked(cadSources).mockRejectedValue(new Error('offline'))
  render(<CadImport projectId="project" robotId="robot" onImported={vi.fn()} />)
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Connected CAD sources could not be loaded'
  )
  expect(startCadImport).not.toHaveBeenCalled()
})
