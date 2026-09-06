import { beforeEach, expect, it, vi } from 'vitest'
import { attachServiceDocument, waitForServiceJob } from './serviceAttachments'
import { api } from '../../lib/api/client'
import * as resources from '../../lib/api/resources'
vi.mock('../../lib/api/resources', () => ({
  createSource: vi.fn(),
  addSourceDocument: vi.fn(),
  triggerSync: vi.fn(),
  getJob: vi.fn()
}))
const connection: resources.Connection = {
  id: 'c1',
  provider: 'onshape',
  status: 'connected',
  account_login: 'builder',
  access: 'read',
  last_error: null,
  needs_reauth: null,
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
const current = (): void => undefined
beforeEach(() => vi.clearAllMocks())
it('reselecting an already tracked document makes zero API calls', async () => {
  const result = await attachServiceDocument({
    projectId: 'p1',
    connection,
    item: { id: 'd1', name: 'Arm' },
    sources: [source],
    client: api,
    assertCurrent: current
  })
  expect(result).toEqual({ source, jobId: null })
  expect(resources.createSource).not.toHaveBeenCalled()
  expect(resources.addSourceDocument).not.toHaveBeenCalled()
  expect(resources.triggerSync).not.toHaveBeenCalled()
})
it('adds a second document to the same account source exactly once', async () => {
  vi.mocked(resources.addSourceDocument).mockResolvedValue({
    source: { ...source, config: { documents: ['d1', 'd2'] } },
    job_id: 'j2',
    status: 'queued'
  })
  const result = await attachServiceDocument({
    projectId: 'p1',
    connection,
    item: { id: 'd2', name: 'Gripper' },
    sources: [source],
    client: api,
    assertCurrent: current
  })
  expect(resources.createSource).not.toHaveBeenCalled()
  expect(resources.addSourceDocument).toHaveBeenCalledWith('p1', 's1', 'd2', api)
  expect(result.jobId).toBe('j2')
  expect(resources.triggerSync).not.toHaveBeenCalled()
})
it('binds the first Onshape document in a different project through I1', async () => {
  vi.mocked(resources.createSource).mockResolvedValue({
    ...source,
    id: 's2',
    project_id: 'p2',
    config: {}
  })
  vi.mocked(resources.addSourceDocument).mockResolvedValue({
    source: { ...source, id: 's2', project_id: 'p2' },
    job_id: 'j2',
    status: 'queued'
  })
  await attachServiceDocument({
    projectId: 'p2',
    connection,
    item: { id: 'd1', name: 'Arm' },
    sources: [],
    client: api,
    assertCurrent: current
  })
  expect(resources.createSource).toHaveBeenCalledWith(
    'p2',
    { type: 'onshape', name: 'Onshape · builder', connection_id: 'c1' },
    api
  )
  expect(resources.addSourceDocument).toHaveBeenCalledWith('p2', 's2', 'd1', api)
})
it('keeps Git repositories independent and never resyncs a matched repository', async () => {
  const git = { ...connection, provider: 'github' }
  const existing = { ...source, type: 'github', config: { repo: 'team/firmware', branch: 'main' } }
  await attachServiceDocument({
    projectId: 'p1',
    connection: git,
    item: { id: 'team/firmware', name: 'Firmware', config: existing.config },
    sources: [existing],
    client: api,
    assertCurrent: current
  })
  expect(resources.triggerSync).not.toHaveBeenCalled()
  vi.mocked(resources.createSource).mockResolvedValue({
    ...existing,
    id: 's2',
    last_synced_at: null,
    config: { repo: 'team/tools', branch: 'main' }
  })
  vi.mocked(resources.triggerSync).mockResolvedValue({ job_id: 'git-job', status: 'queued' })
  await attachServiceDocument({
    projectId: 'p1',
    connection: git,
    item: { id: 'team/tools', name: 'Tools', config: { repo: 'team/tools', branch: 'main' } },
    sources: [existing],
    client: api,
    assertCurrent: current
  })
  expect(resources.triggerSync).toHaveBeenCalledWith('p1', 's2', api)
  expect(resources.addSourceDocument).not.toHaveBeenCalled()
})
it('refuses a stale scope between binding and selecting a document', async () => {
  vi.mocked(resources.createSource).mockResolvedValue({ ...source, config: {} })
  const assertCurrent = vi
    .fn()
    .mockImplementationOnce(current)
    .mockImplementation(() => {
      throw new Error('Session changed')
    })
  await expect(
    attachServiceDocument({
      projectId: 'p1',
      connection,
      item: { id: 'd2', name: 'Arm' },
      sources: [],
      client: api,
      assertCurrent
    })
  ).rejects.toThrow('Session changed')
  expect(resources.addSourceDocument).not.toHaveBeenCalled()
})
it('observes only the accepted job until success, without triggering sync', async () => {
  vi.mocked(resources.getJob)
    .mockResolvedValueOnce({ id: 'j1', project_id: 'p1', status: 'running', error: null })
    .mockResolvedValue({ id: 'j1', project_id: 'p1', status: 'succeeded', error: null })
  await waitForServiceJob({
    projectId: 'p1',
    jobId: 'j1',
    client: api,
    assertCurrent: current,
    sleep: async () => undefined
  })
  expect(resources.getJob).toHaveBeenCalledTimes(2)
  expect(resources.triggerSync).not.toHaveBeenCalled()
})
it('reports job failure and refuses a job from another project', async () => {
  vi.mocked(resources.getJob).mockResolvedValue({
    id: 'j1',
    project_id: 'p1',
    status: 'failed',
    error: { message: 'Quota unavailable' }
  })
  await expect(
    waitForServiceJob({ projectId: 'p1', jobId: 'j1', client: api, assertCurrent: current })
  ).rejects.toThrow('Quota unavailable')
  vi.mocked(resources.getJob).mockResolvedValue({
    id: 'j1',
    project_id: 'other',
    status: 'succeeded',
    error: null
  })
  await expect(
    waitForServiceJob({ projectId: 'p1', jobId: 'j1', client: api, assertCurrent: current })
  ).rejects.toThrow('project')
})
