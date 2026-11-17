import { expect, it, vi } from 'vitest'
import { readHardwareTopology } from './hardwareTopology'
import type { ApiClient } from './client'

it('uses the centralized scoped client, encoded IDs and abort signal', async () => {
  const data = { robot_id: 'r/1', nodes: [], edges: [], roots: [] }
  const request = vi.fn().mockResolvedValue(data)
  const client = { request } as unknown as ApiClient
  const controller = new AbortController()
  expect(await readHardwareTopology('p/1', 'r/1', controller.signal, client)).toEqual(data)
  expect(request).toHaveBeenCalledWith('/projects/p%2F1/hardware/robots/r%2F1/topology', {
    signal: controller.signal
  })
})
it('rejects a response for another robot', async () => {
  const client = {
    request: vi.fn().mockResolvedValue({ robot_id: 'other', nodes: [], edges: [], roots: [] })
  } as unknown as ApiClient
  await expect(readHardwareTopology('p', 'r', undefined, client)).rejects.toThrow(
    'Invalid hardware topology'
  )
})
it('rejects malformed node metadata before rendering', async () => {
  const client = {
    request: vi.fn().mockResolvedValue({
      robot_id: 'r',
      nodes: [{ id: 'n', role: 'invented' }],
      edges: [],
      roots: []
    })
  } as unknown as ApiClient
  await expect(readHardwareTopology('p', 'r', undefined, client)).rejects.toThrow(
    'Invalid hardware topology'
  )
})

it('accepts omitted optional metadata from the generated API schema', async () => {
  const data = {
    robot_id: 'r',
    nodes: [{ id: 'node', name: 'Controller', role: 'brain' }],
    edges: [],
    roots: ['node']
  }
  const client = { request: vi.fn().mockResolvedValue(data) } as unknown as ApiClient
  expect(await readHardwareTopology('p', 'r', undefined, client)).toEqual(data)
})

it('accepts onboard brains and a measured clock and refuses a malformed clock', async () => {
  const clock = {
    offset_ms: -12.5,
    jitter_ms: 0.8,
    measured_at: '2026-11-15T10:00:00Z',
    method: 'rtt8'
  }
  const brain = { id: 'computer', name: 'ip:10.0.0.2', role: 'brain', brain_kind: 'onboard' }
  const read = (node: Record<string, unknown>): Promise<unknown> =>
    readHardwareTopology('p', 'r', undefined, {
      request: vi.fn().mockResolvedValue({ robot_id: 'r', nodes: [node], edges: [], roots: [] })
    } as unknown as ApiClient)
  expect((await read({ ...brain, clock })) as object).toMatchObject({ nodes: [{ clock }] })
  expect(await read({ ...brain, clock: null })).toBeTruthy()
  for (const bad of [
    { ...clock, offset_ms: 'soon' },
    { ...clock, jitter_ms: Number.NaN },
    { ...clock, measured_at: 7 },
    'yesterday'
  ])
    await expect(read({ ...brain, clock: bad })).rejects.toThrow('Invalid hardware topology')
})
