// The Build step reads REAL sync state (SOLUSDEV-152 de-simulation): one line
// per source from the live API, polled to terminal where a sync is in flight,
// and an entity count read from the graph — never fabricated numbers.
import { describe, it, expect, vi } from 'vitest'
import type { Source, Sync } from '../../lib/api/resources'
import type { BuildLine } from './onboardingStore'
import { runBuildProgress, type BuildProgressApi } from './buildProgress'

const noSleep = async (): Promise<void> => undefined

function source(id: string, name: string): Source {
  return {
    id,
    project_id: 'p1',
    type: 'github',
    name,
    status: 'connected',
    config: {},
    account_login: null,
    last_synced_at: null,
    last_error: null,
    created_at: '2026-01-01',
    updated_at: '2026-01-01'
  }
}

function sync(status: Sync['status'], entities = 0, relations = 0, errors: unknown[] = []): Sync {
  return { id: 'sy1', status, entities_created: entities, relations_created: relations, errors }
}

function makeApi(overrides: Partial<BuildProgressApi> = {}): BuildProgressApi {
  return {
    listSources: vi.fn(async () => [source('s1', 'strider-fw')]),
    getSyncs: vi.fn(async () => [sync('succeeded', 214, 12)]),
    listEntities: vi.fn(async () => Array.from({ length: 5 }, (_, i) => ({ id: `e${i}` }))),
    ...overrides
  } as BuildProgressApi
}

function collect(): {
  batches: (readonly BuildLine[])[]
  onLines: (l: readonly BuildLine[]) => void
} {
  const batches: (readonly BuildLine[])[] = []
  return { batches, onLines: (l) => batches.push(l) }
}

describe('runBuildProgress', () => {
  it('returns an empty honest result when the project has no sources', async () => {
    const api = makeApi({ listSources: vi.fn(async () => []) })
    const { batches, onLines } = collect()

    const result = await runBuildProgress({ api, onLines, sleep: noSleep }, 'p1')

    expect(result.lines).toEqual([])
    expect(result.entityCount).toBeUndefined()
    expect(batches).toEqual([[]])
  })

  it('reports one ok line per synced source with its real counts', async () => {
    const api = makeApi()
    const { batches, onLines } = collect()

    const result = await runBuildProgress({ api, onLines, sleep: noSleep }, 'p1')

    expect(result.lines).toEqual([
      { name: 'strider-fw', detail: '214 entities · 12 relations', state: 'ok' }
    ])
    // First batch is the pending snapshot, later batches resolve it.
    expect(batches[0][0].state).toBe('pending')
    expect(result.entityCount).toBe(5)
  })

  it('polls an in-flight sync to terminal before reporting it', async () => {
    const getSyncs = vi
      .fn<(projectId: string, sourceId: string) => Promise<Sync[]>>()
      .mockResolvedValueOnce([sync('running')])
      .mockResolvedValueOnce([sync('running')])
      .mockResolvedValue([sync('succeeded', 47, 16)])
    const api = makeApi({ getSyncs })
    const { onLines } = collect()

    const result = await runBuildProgress({ api, onLines, sleep: noSleep }, 'p1')

    expect(result.lines[0]).toEqual({
      name: 'strider-fw',
      detail: '47 entities · 16 relations',
      state: 'ok'
    })
    expect(getSyncs.mock.calls.length).toBeGreaterThan(1)
  })

  it('reports a failed sync with its real error message', async () => {
    const api = makeApi({
      getSyncs: vi.fn(async () => [sync('failed', 0, 0, ['Bad netlist header'])])
    })
    const { onLines } = collect()

    const result = await runBuildProgress({ api, onLines, sleep: noSleep }, 'p1')

    expect(result.lines[0]).toEqual({
      name: 'strider-fw',
      detail: 'Bad netlist header',
      state: 'failed'
    })
  })

  it('marks a source with no recorded sync as idle, never fabricating progress', async () => {
    const api = makeApi({ getSyncs: vi.fn(async () => []) })
    const { onLines } = collect()

    const result = await runBuildProgress({ api, onLines, sleep: noSleep }, 'p1')

    expect(result.lines[0]).toEqual({
      name: 'strider-fw',
      detail: 'No sync recorded yet',
      state: 'idle'
    })
  })

  it('marks a sync that outlives the poll window as still running (idle)', async () => {
    const api = makeApi({ getSyncs: vi.fn(async () => [sync('running')]) })
    const { onLines } = collect()

    const result = await runBuildProgress({ api, onLines, sleep: noSleep }, 'p1')

    expect(result.lines[0].state).toBe('idle')
    expect(result.lines[0].detail).toMatch(/still running/i)
  })

  it('resolves an error result when sources cannot be listed — never throws', async () => {
    const api = makeApi({
      listSources: vi.fn(async () => {
        throw new Error('API unreachable')
      })
    })
    const { onLines } = collect()

    const result = await runBuildProgress({ api, onLines, sleep: noSleep }, 'p1')

    expect(result.lines).toEqual([])
    expect(result.error).toBe('API unreachable')
  })

  it('marks a source failed when its sync history cannot be read', async () => {
    const api = makeApi({
      getSyncs: vi.fn(async () => {
        throw new Error('403 forbidden')
      })
    })
    const { onLines } = collect()

    const result = await runBuildProgress({ api, onLines, sleep: noSleep }, 'p1')

    expect(result.lines[0].state).toBe('failed')
    expect(result.lines[0].detail).toBe('403 forbidden')
  })

  it('leaves the entity count unknown when the graph cannot be read', async () => {
    const api = makeApi({
      listEntities: vi.fn(async () => {
        throw new Error('offline')
      })
    })
    const { onLines } = collect()

    const result = await runBuildProgress({ api, onLines, sleep: noSleep }, 'p1')

    expect(result.entityCount).toBeUndefined()
    expect(result.lines[0].state).toBe('ok')
  })
})
