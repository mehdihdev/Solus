import { act, fireEvent, render, screen, within, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { RunsView } from './RunsView'
import * as runs from './runsApi'
import { listEntities, uploadArtifact, type BenchSession } from '../../../lib/api/resources'
import { useWorkspaceStore } from '../../../store/workspaceStore'
vi.mock('./runsApi', () => ({
  listRuns: vi.fn(),
  startRun: vi.fn(),
  stopRun: vi.fn(),
  importRun: vi.fn(),
  getRun: vi.fn(),
  runFindings: vi.fn(),
  compareRuns: vi.fn()
}))
vi.mock('../../../lib/api/resources', () => ({
  listEntities: vi.fn(),
  uploadArtifact: vi.fn(),
  ARTIFACT_MAX_BYTES: 8388608
}))
const summary = {
  id: 'run',
  robot_id: 'robot',
  session_id: 'session',
  name: 'Capture',
  origin: 'live' as const,
  status: 'running' as const,
  started_at: '2026-01-01T00:00:00Z',
  ended_at: null,
  packet_count: 3,
  drop_count: 0,
  artifact_id: null
}
const session = {
  id: 'session',
  provider: 'robot',
  status: 'active',
  label: 'Follower',
  mode: 'real',
  link: 'streaming',
  device_ids: ['servo'],
  counts: { ingested: 1, unresolved: 0 },
  device: null,
  created_at: '',
  ended_at: null,
  last_summary: null
} satisfies BenchSession
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(runs.listRuns).mockResolvedValue({ runs: [], next_cursor: null })
  vi.mocked(listEntities).mockResolvedValue([
    {
      id: 'robot',
      name: 'Follower',
      type: 'physical_robot',
      origin: 'manual',
      source_id: null,
      project_id: 'p'
    }
  ] as Awaited<ReturnType<typeof listEntities>>)
  vi.mocked(runs.startRun).mockResolvedValue(summary)
  vi.mocked(runs.stopRun).mockResolvedValue({
    ...summary,
    status: 'completed',
    artifact_id: 'saved'
  })
})
it('records only an explicitly selected active saved-robot session and stops without motion', async () => {
  render(<RunsView projectId="p" sessions={[session]} />)
  await within(screen.getByLabelText('Run robot')).findByRole('option', { name: 'Follower' })
  fireEvent.change(screen.getByLabelText('Run robot'), { target: { value: 'robot' } })
  fireEvent.change(screen.getByLabelText('Recording session'), { target: { value: 'session' } })
  fireEvent.change(screen.getByLabelText('Run name'), { target: { value: 'Capture' } })
  fireEvent.click(screen.getByRole('button', { name: 'Start recording' }))
  await screen.findByRole('button', { name: 'Stop Capture' })
  expect(runs.startRun).toHaveBeenCalledWith('p', {
    robot_id: 'robot',
    session_id: 'session',
    name: 'Capture'
  })
  fireEvent.click(screen.getByRole('button', { name: 'Stop Capture' }))
  await screen.findByText(/completed/)
  expect(runs.stopRun).toHaveBeenCalledWith('p', 'run')
})
it('never imports after the project changes while a local upload is pending', async () => {
  let finish!: (value: Awaited<ReturnType<typeof uploadArtifact>>) => void
  vi.mocked(uploadArtifact).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve
    })
  )
  useWorkspaceStore.setState({ project: { id: 'p', name: 'P' } })
  render(<RunsView projectId="p" sessions={[]} />)
  await within(screen.getByLabelText('Run robot')).findByRole('option', { name: 'Follower' })
  fireEvent.change(screen.getByLabelText('Run robot'), { target: { value: 'robot' } })
  fireEvent.change(screen.getByLabelText('Run name'), { target: { value: 'Recorded' } })
  fireEvent.change(screen.getByLabelText('Run manifest file'), {
    target: { files: [new File(['{}'], 'run.json', { type: 'application/json' })] }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Import recording' }))
  await waitFor(() => expect(uploadArtifact).toHaveBeenCalledTimes(1))
  act(() => {
    useWorkspaceStore.setState({ project: { id: 'q', name: 'Q' } })
    useWorkspaceStore.setState({ project: { id: 'p', name: 'P' } })
  })
  await act(async () => {
    finish({
      artifact_id: 'a',
      uri: '',
      media_type: 'application/json',
      storage: 'local',
      size_bytes: 2,
      summary: null
    })
  })
  expect(runs.importRun).not.toHaveBeenCalled()
})

it('rejects oversized local manifests before uploading', async () => {
  render(<RunsView projectId="p" sessions={[]} />)
  await within(screen.getByLabelText('Run robot')).findByRole('option', { name: 'Follower' })
  fireEvent.change(screen.getByLabelText('Run robot'), { target: { value: 'robot' } })
  fireEvent.change(screen.getByLabelText('Run name'), { target: { value: 'Large' } })
  const file = new File(['{}'], 'large.json')
  Object.defineProperty(file, 'size', { value: 8388609 })
  fireEvent.change(screen.getByLabelText('Run manifest file'), { target: { files: [file] } })
  fireEvent.click(screen.getByRole('button', { name: 'Import recording' }))
  expect(await screen.findByText(/at most 8 MiB/)).toBeInTheDocument()
  expect(uploadArtifact).not.toHaveBeenCalled()
})

it('does not offer ended or generic serial sessions as recording targets', async () => {
  render(
    <RunsView
      projectId="p"
      sessions={[
        { ...session, status: 'ended' },
        { ...session, id: 'serial', provider: 'serial', label: 'Generic serial' }
      ]}
    />
  )
  await screen.findByText('No runs have been captured or imported in this project.')
  expect(
    within(screen.getByLabelText('Recording session')).queryByRole('option', {
      name: 'Generic serial'
    })
  ).not.toBeInTheDocument()
  expect(
    within(screen.getByLabelText('Recording session')).queryByRole('option', { name: 'Follower' })
  ).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Start recording' })).toBeDisabled()
  expect(screen.getByText(/No active saved-robot session/)).toBeInTheDocument()
})
