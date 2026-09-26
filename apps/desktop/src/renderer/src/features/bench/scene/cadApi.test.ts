import { expect, it, vi } from 'vitest'
import { api } from '../../../lib/api/client'
import { cadSources, bindCad, startCadImport, cadImportStatus } from './cadApi'
vi.mock('../../../lib/api/client', () => ({ api: { request: vi.fn() } }))
it.each([
  { sources: [{ id: 's', name: {}, observed_microversion: 'v' }] },
  { sources: Array(257).fill({ id: 's', name: 'CAD', observed_microversion: 'v' }) },
  []
])('rejects invalid CAD source responses', async (value) => {
  vi.mocked(api.request).mockResolvedValue(value)
  await expect(cadSources('p')).rejects.toThrow()
})

const sceneModel = {
  id: 'm',
  robot_id: 'r',
  name: 'Arm',
  artifact_id: 'a',
  version: 2,
  source_current: true,
  bindings: [],
  model: { links: [], joints: [], warnings: [] }
}
it.each(['current', 'queued', 'stale', 'error'] as const)(
  'accepts the actual CAD refresh status %s',
  async (refresh_status) => {
    vi.mocked(api.request).mockResolvedValue({ model: sceneModel, refresh_status, job_id: null })
    await expect(bindCad('p', 'm', 1, [])).resolves.toMatchObject({ refresh_status })
  }
)
it.each([{}, 'done', null, 1])('rejects invalid CAD refresh status', async (refresh_status) => {
  vi.mocked(api.request).mockResolvedValue({ model: sceneModel, refresh_status, job_id: null })
  await expect(bindCad('p', 'm', 1, [])).rejects.toThrow()
})

const importStatus = {
  import_id: 'i',
  status: 'pending',
  reason: null,
  job_id: null,
  model_id: null
}
it('includes assembly sources only when explicitly requested', async () => {
  vi.mocked(api.request).mockResolvedValue({ sources: [] })
  await cadSources('p')
  expect(api.request).toHaveBeenLastCalledWith('/projects/p/bench/scene/cad-sources', {
    signal: undefined
  })
  await cadSources('p', undefined, true)
  expect(api.request).toHaveBeenLastCalledWith(
    '/projects/p/bench/scene/cad-sources?include_assemblies=true',
    { signal: undefined }
  )
})
it('submits an explicit revision-bound CAD import and carries cancellation', async () => {
  vi.mocked(api.request).mockResolvedValue(importStatus)
  const signal = new AbortController().signal
  const input = { robot_id: 'r', source_entity_id: 's', expected_revision: 'v' }
  await expect(startCadImport('p', input, signal)).resolves.toEqual(importStatus)
  expect(api.request).toHaveBeenLastCalledWith('/projects/p/bench/scene/cad-imports', {
    method: 'POST',
    body: input,
    signal
  })
  await expect(startCadImport('p', { ...input, expected_revision: '' })).rejects.toThrow()
})
it.each([
  { ...importStatus, import_id: 'other' },
  { ...importStatus, status: 'complete' },
  { ...importStatus, status: 'invented' },
  { ...importStatus, reason: {} },
  { ...importStatus, status: { toString: () => 'pending' } }
])('refuses malformed or mismatched import status', async (value) => {
  vi.mocked(api.request).mockResolvedValue(value)
  await expect(cadImportStatus('p', 'i')).rejects.toThrow()
})
