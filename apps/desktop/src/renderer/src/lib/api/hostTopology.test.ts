import { expect, it, vi } from 'vitest'
import { proposeHostTopology, confirmHostTopology } from './hostTopology'
import type { ApiClient } from './client'
const input = {
  endpoint_id: 'endpoint',
  machine_id: 'machine',
  local_source_id: 'source',
  software_entity_id: 'file'
}
const topology = { robot_id: 'robot', nodes: [], edges: [], roots: [] }
it('validates proposal scope and only sends the selected graph identities', async () => {
  const request = vi.fn().mockResolvedValue({
    ...input,
    host_name: 'Computer',
    proposal_digest: 'a'.repeat(64),
    notes: [],
    topology
  })
  await proposeHostTopology('project', 'robot', input, undefined, {
    request
  } as unknown as ApiClient)
  expect(request).toHaveBeenCalledWith(
    '/projects/project/hardware/robots/robot/topology/host/propose',
    { method: 'POST', body: input, signal: undefined }
  )
  request.mockResolvedValue({
    ...input,
    endpoint_id: 'elsewhere',
    host_name: 'Computer',
    proposal_digest: 'a'.repeat(64),
    notes: [],
    topology
  })
  await expect(
    proposeHostTopology('project', 'robot', input, undefined, { request } as unknown as ApiClient)
  ).rejects.toThrow('Invalid host proposal')
})
it('sends confirmation through the authenticated API transport with a stable operation key', async () => {
  const fetchImpl = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify({ data: topology }), { status: 200 }))
  await confirmHostTopology(
    'project',
    'robot',
    { ...input, proposal_digest: 'a'.repeat(64) },
    'operation',
    undefined,
    { fetchImpl, getToken: async () => 'test-token', baseUrl: 'https://api.test/api/v1' }
  )
  expect(fetchImpl).toHaveBeenCalledWith(
    'https://api.test/api/v1/projects/project/hardware/robots/robot/topology/host/confirm',
    expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer test-token',
        'Idempotency-Key': 'operation'
      })
    })
  )
})

it('does not send confirmation when scope is aborted while acquiring authentication', async () => {
  const controller = new AbortController()
  const fetchImpl = vi.fn()
  await expect(
    confirmHostTopology(
      'project',
      'robot',
      { ...input, proposal_digest: 'a'.repeat(64) },
      'operation',
      controller.signal,
      {
        fetchImpl,
        getToken: async () => {
          controller.abort()
          return 'test-token'
        }
      }
    )
  ).rejects.toThrow()
  expect(fetchImpl).not.toHaveBeenCalled()
})

it('rejects malformed or cross-robot confirmation results and propagates authorization errors', async () => {
  const fetchImpl = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify({ data: { ...topology, robot_id: 'other' } }), { status: 200 })
    )
  const confirm = (): Promise<unknown> =>
    confirmHostTopology(
      'project',
      'robot',
      { ...input, proposal_digest: 'a'.repeat(64) },
      'operation',
      undefined,
      { fetchImpl, getToken: async () => null }
    )
  await expect(confirm()).rejects.toThrow('Invalid confirmed host topology')
  fetchImpl.mockResolvedValue(
    new Response(JSON.stringify({ error: { code: 'forbidden', message: 'Forbidden' } }), {
      status: 403
    })
  )
  await expect(confirm()).rejects.toMatchObject({ status: 403 })
})
