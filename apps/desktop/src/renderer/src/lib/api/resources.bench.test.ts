// SOLUSDEV-72 — typed wrappers for the local-connection bench routes (sources,
// sessions, device-recent) and the local-tools registry. Contracts are frozen;
// these tests pin paths, methods, and body passthrough.
import { describe, it, expect, vi } from 'vitest'
import {
  getBenchSources,
  createBenchSession,
  listBenchSessions,
  getBenchSession,
  stopBenchSession,
  getBenchDeviceRecent,
  listLocalTools
} from './resources'
import type { ApiClient } from './client'

function stubClient(result: unknown): {
  client: ApiClient
  calls: { path: string; options?: unknown }[]
} {
  const calls: { path: string; options?: unknown }[] = []
  const client: ApiClient = {
    request: vi.fn(async (path: string, options?: unknown) => {
      calls.push({ path, options })
      return result as never
    }),
    requestPage: vi.fn(async (path: string, options?: unknown) => {
      calls.push({ path, options })
      return { data: result, meta: {} } as never
    })
  }
  return { client, calls }
}

describe('bench source + session calls', () => {
  it('getBenchSources hits the project bench sources route', async () => {
    const { client, calls } = stubClient({ runner: { available: true, reason: null } })
    await getBenchSources('p1', client)
    expect(calls[0].path).toBe('/projects/p1/bench/sources')
  })

  it('createBenchSession POSTs the sim config unchanged', async () => {
    const { client, calls } = stubClient({ id: 's1' })
    await createBenchSession('p1', { mode: 'sim', config: { provider: 'mujoco' } }, client)
    expect(calls[0].path).toBe('/projects/p1/bench/sessions')
    expect(calls[0].options).toMatchObject({
      method: 'POST',
      body: { mode: 'sim', config: { provider: 'mujoco' } }
    })
  })

  it('createBenchSession POSTs the real/serial config unchanged', async () => {
    const { client, calls } = stubClient({ id: 's1' })
    await createBenchSession(
      'p1',
      { mode: 'real', config: { provider: 'serial', serial_number: '5B42135040' } },
      client
    )
    expect(calls[0].options).toMatchObject({
      method: 'POST',
      body: { mode: 'real', config: { provider: 'serial', serial_number: '5B42135040' } }
    })
  })

  it('listBenchSessions filters by status and mode via query params', async () => {
    const { client, calls } = stubClient([])
    await listBenchSessions('p1', {}, client)
    expect(calls[0].path).toBe('/projects/p1/bench/sessions')
    await listBenchSessions('p1', { status: 'active', mode: 'real' }, client)
    expect(calls[1].path).toBe('/projects/p1/bench/sessions?status=active&mode=real')
  })

  it('getBenchSession hits the session detail route', async () => {
    const { client, calls } = stubClient({ id: 's1' })
    await getBenchSession('p1', 's1', client)
    expect(calls[0].path).toBe('/projects/p1/bench/sessions/s1')
  })

  it('stopBenchSession POSTs the idempotent stop route', async () => {
    const { client, calls } = stubClient({ id: 's1', status: 'ended' })
    await stopBenchSession('p1', 's1', client)
    expect(calls[0].path).toBe('/projects/p1/bench/sessions/s1/stop')
    expect((calls[0].options as { method?: string }).method).toBe('POST')
  })

  it('getBenchDeviceRecent batches ids as repeated params and unwraps devices', async () => {
    const entry = { device_id: 'demo/rod', resolved_entity_id: null, signals: [] }
    const { client, calls } = stubClient({ devices: [entry] })
    const result = await getBenchDeviceRecent('p1', ['demo/rod', 'demo/arm'], { limit: 50 }, client)
    expect(calls[0].path).toBe(
      '/projects/p1/bench/device-recent?device_id=demo%2Frod&device_id=demo%2Farm&limit=50'
    )
    expect(result).toEqual([entry])
  })

  it('getBenchDeviceRecent omits limit when not given', async () => {
    const { client, calls } = stubClient({ devices: [] })
    await getBenchDeviceRecent('p1', ['d1'], {}, client)
    expect(calls[0].path).toBe('/projects/p1/bench/device-recent?device_id=d1')
  })
})

describe('local tools', () => {
  it('listLocalTools hits the unscoped local-tools route', async () => {
    const { client, calls } = stubClient([])
    await listLocalTools(client)
    expect(calls[0].path).toBe('/integrations/local-tools')
  })
})
