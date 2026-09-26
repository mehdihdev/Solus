import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../../lib/api/client'
import { compareRuns, getRun, importRun, listRuns, runFindings, startRun, stopRun } from './runsApi'
vi.mock('../../../lib/api/client', () => ({ api: { request: vi.fn().mockResolvedValue({}) } }))
beforeEach(() => vi.clearAllMocks())
const summary = {
  id: '11111111-1111-4111-8111-111111111111',
  robot_id: '11111111-1111-4111-8111-111111111111',
  session_id: null,
  artifact_id: null,
  name: 'Run',
  origin: 'synthetic',
  status: 'completed',
  started_at: '2026-01-01T00:00:00Z',
  ended_at: null,
  packet_count: 0,
  drop_count: 0
}
it('uses only project-scoped recording/read routes with explicit identifiers', async () => {
  vi.mocked(api.request).mockResolvedValue({ runs: [], next_cursor: null })
  await listRuns('p', 'next cursor')
  expect(api.request).toHaveBeenLastCalledWith(
    '/projects/p/bench/runs?limit=50&cursor=next+cursor',
    { signal: undefined }
  )
  vi.mocked(api.request).mockResolvedValue(summary)
  await startRun('p', { robot_id: 'r', session_id: 's', name: 'Capture' })
  expect(api.request).toHaveBeenLastCalledWith('/projects/p/bench/runs', {
    method: 'POST',
    body: { robot_id: 'r', session_id: 's', name: 'Capture' }
  })
  await stopRun('p', 'run')
  expect(api.request).toHaveBeenLastCalledWith('/projects/p/bench/runs/run/stop', {
    method: 'POST'
  })
  await importRun('p', { robot_id: 'r', artifact_id: 'a', name: 'Fixture', origin: 'synthetic' })
  expect(api.request).toHaveBeenLastCalledWith('/projects/p/bench/runs/import', {
    method: 'POST',
    body: { robot_id: 'r', artifact_id: 'a', name: 'Fixture', origin: 'synthetic' }
  })
  vi.mocked(api.request).mockResolvedValue({
    config_changes: [],
    source_snapshots_changed: false,
    divergences: [],
    clamp_attributions: [],
    insufficient: []
  })
  await compareRuns('p', 'before', 'after')
  expect(api.request).toHaveBeenLastCalledWith('/projects/p/bench/runs/compare', {
    method: 'POST',
    body: { baseline_id: 'before', candidate_id: 'after' }
  })
  const signal = new AbortController().signal
  vi.mocked(api.request).mockResolvedValue({
    summary,
    manifest: {
      schema_version: 1,
      robot_id: summary.robot_id,
      started_at: summary.started_at,
      packets: [],
      sensors: [],
      parts: [],
      snapshots: []
    }
  })
  await getRun('p', 'a/b', signal)
  expect(api.request).toHaveBeenLastCalledWith('/projects/p/bench/runs/a%2Fb', { signal })
  vi.mocked(api.request).mockResolvedValue({ findings: [], insufficient: [] })
  await runFindings('p', 'a/b', signal)
  expect(api.request).toHaveBeenLastCalledWith('/projects/p/bench/runs/a%2Fb/findings', { signal })
})
