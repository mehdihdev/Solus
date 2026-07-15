// Tests for the real committed-export EDA connect orchestration (SOLUSDEV-100).
// Drives the flow with a stubbed API surface: create the source with the export
// content, sync, poll to a terminal state, and report progress/result — the
// EDA sibling of githubConnect.test.ts. No React, no network.
import { describe, it, expect, vi } from 'vitest'
import type { Source, Sync } from '../../lib/api/resources'
import type { ConnectionState } from './onboardingStore'
import { runEdaConnect, MAX_EXPORT_BYTES, type EdaConnectApi } from './edaConnect'

const NETLIST = '<export version="E"><components/><nets/></export>'

function source(overrides: Partial<Source> = {}): Source {
  return {
    id: 's1',
    project_id: 'p1',
    type: 'kicad',
    name: 'power-board',
    status: 'connected',
    config: {},
    account_login: null,
    last_synced_at: null,
    last_error: null,
    created_at: '',
    updated_at: '',
    ...overrides
  }
}

function sync(overrides: Partial<Sync> = {}): Sync {
  return {
    id: 'sy1',
    status: 'succeeded',
    entities_created: 6,
    relations_created: 4,
    errors: [],
    ...overrides
  }
}

function stubApi(overrides: Partial<EdaConnectApi> = {}): EdaConnectApi {
  return {
    createSource: vi.fn(async () => source()),
    triggerSync: vi.fn(async () => ({ job_id: 'j1', status: 'queued' })),
    getSyncs: vi.fn(async () => [sync()]),
    getSource: vi.fn(async () => source({ entity_count: 6 })),
    ...overrides
  }
}

function collect(): { states: ConnectionState[]; onProgress: (s: ConnectionState) => void } {
  const states: ConnectionState[] = []
  return { states, onProgress: (s) => states.push(s) }
}

const noSleep = async (): Promise<void> => {}

describe('runEdaConnect', () => {
  it('creates the source with the export content, syncs, and reports done', async () => {
    const api = stubApi()
    const { states, onProgress } = collect()

    const result = await runEdaConnect({ api, onProgress, sleep: noSleep }, 'p1', 'kicad', {
      fileName: 'power-board.xml',
      content: NETLIST
    })

    expect(api.createSource).toHaveBeenCalledWith('p1', {
      type: 'kicad',
      name: 'power-board',
      config: { export: NETLIST }
    })
    expect(api.triggerSync).toHaveBeenCalledWith('p1', 's1')
    expect(result.ok).toBe(true)
    expect(result.result).toContain('6')
    const last = states[states.length - 1]
    expect(last.phase).toBe('done')
  })

  it('reports the backend error message when the sync fails', async () => {
    // e.g. an S-expr .net upload: the backend rejects with re-export guidance.
    const message =
      'kicad: the S-expression netlist is not supported in v1; re-export as XML ' +
      'with `kicad-cli sch export netlist --format kicadxml`.'
    const api = stubApi({
      getSyncs: vi.fn(async () => [sync({ status: 'failed', errors: [{ item: 'sync', message }] })])
    })
    const { states, onProgress } = collect()

    const result = await runEdaConnect({ api, onProgress, sleep: noSleep }, 'p1', 'kicad', {
      fileName: 'board.net',
      content: '(export (version "E"))'
    })

    expect(result.ok).toBe(false)
    expect(result.error).toContain('kicad-cli')
    expect(states[states.length - 1].phase).toBe('error')
  })

  it('refuses an empty file without calling the API', async () => {
    const api = stubApi()
    const { states, onProgress } = collect()

    const result = await runEdaConnect({ api, onProgress, sleep: noSleep }, 'p1', 'kicad', {
      fileName: 'empty.xml',
      content: ''
    })

    expect(result.ok).toBe(false)
    expect(api.createSource).not.toHaveBeenCalled()
    expect(states[states.length - 1].phase).toBe('error')
  })

  it('refuses an oversized export without calling the API (backend bound mirrored)', async () => {
    const api = stubApi()
    const { onProgress } = collect()

    const result = await runEdaConnect({ api, onProgress, sleep: noSleep }, 'p1', 'kicad', {
      fileName: 'huge.xml',
      content: 'x'.repeat(MAX_EXPORT_BYTES + 1)
    })

    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/too large/i)
    expect(api.createSource).not.toHaveBeenCalled()
  })

  it('reports a timeout when the sync never reaches a terminal state', async () => {
    const api = stubApi({ getSyncs: vi.fn(async () => [sync({ status: 'running' })]) })
    const { onProgress } = collect()

    const result = await runEdaConnect({ api, onProgress, sleep: noSleep }, 'p1', 'kicad', {
      fileName: 'power-board.xml',
      content: NETLIST
    })

    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/timed out/i)
  })

  it('resolves to an error instead of throwing when the API rejects', async () => {
    const api = stubApi({
      createSource: vi.fn(async () => {
        throw new Error("No connector for 'kicad'")
      })
    })
    const { states, onProgress } = collect()

    const result = await runEdaConnect({ api, onProgress, sleep: noSleep }, 'p1', 'kicad', {
      fileName: 'power-board.xml',
      content: NETLIST
    })

    expect(result.ok).toBe(false)
    expect(result.error).toContain("No connector for 'kicad'")
    expect(states[states.length - 1].phase).toBe('error')
  })
})
