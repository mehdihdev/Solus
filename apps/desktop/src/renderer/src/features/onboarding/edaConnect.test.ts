// Tests for the real committed-export EDA connect orchestration (SOLUSDEV-100).
// Drives the flow with a stubbed API surface: create the source with the export
// content, sync, poll to a terminal state, and report progress/result — the
// EDA sibling of githubConnect.test.ts. No React, no network.
import { describe, it, expect, vi } from 'vitest'
import type { Source, Sync } from '../../lib/api/resources'
import type { ConnectionState } from './onboardingStore'
import {
  runEdaConnect,
  EMPTY_EXPORT_ERROR,
  MAX_EXPORT_BYTES,
  OVERSIZE_EXPORT_ERROR,
  type EdaConnectApi
} from './edaConnect'
import { NO_FILES_ERROR } from './kicadFiles'

const NETLIST = '<export version="E"><components/><nets/></export>'
const BOARD = '(kicad_pcb (version 20240108) (footprint "R_0603"))'
const XML_FILE = { fileName: 'power-board.xml', content: NETLIST }
const BOARD_FILE = { fileName: 'power-board.kicad_pcb', content: BOARD }

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
    getJob: vi.fn(async () => ({
      id: 'j1',
      project_id: 'p1',
      status: 'succeeded' as const,
      error: null
    })),
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
  registerExportSourceCreationTests()

  registerCombinedExportSyncTests()

  registerExportBoundsTests()

  registerExportSyncFailuresTests()
})

function registerExportSourceCreationTests(): void {
  it('creates the source with the netlist as config.export, syncs, and reports done', async () => {
    const api = stubApi()
    const { states, onProgress } = collect()

    const result = await runEdaConnect({ api, onProgress, sleep: noSleep }, 'p1', 'kicad', {
      netlist: XML_FILE
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

  it('omits `board` entirely for a netlist-only pick (no undefined values in config)', async () => {
    const api = stubApi()
    await runEdaConnect({ api, onProgress: collect().onProgress, sleep: noSleep }, 'p1', 'kicad', {
      netlist: XML_FILE
    })
    const [, input] = vi.mocked(api.createSource).mock.calls[0]
    expect(input.config).toEqual({ export: NETLIST })
    expect('board' in input.config!).toBe(false)
    expect(Object.values(input.config!)).not.toContain(undefined)
  })

  it('sends a board-only pick as config.board, naming the source after the board file', async () => {
    const api = stubApi()
    const { states, onProgress } = collect()

    const result = await runEdaConnect({ api, onProgress, sleep: noSleep }, 'p1', 'kicad', {
      board: BOARD_FILE
    })

    const [, input] = vi.mocked(api.createSource).mock.calls[0]
    expect(input).toEqual({ type: 'kicad', name: 'power-board', config: { board: BOARD } })
    expect('export' in input.config!).toBe(false)
    expect(result.ok).toBe(true)
    expect(states.map((s) => (s.phase === 'busy' ? s.label : s.phase))).toEqual([
      'Reading power-board.kicad_pcb…',
      'Parsing board & building the graph…',
      'done'
    ])
  })
}

function registerCombinedExportSyncTests(): void {
  it('sends netlist and board together, one key each, named after the netlist', async () => {
    const api = stubApi()
    const { states, onProgress } = collect()

    await runEdaConnect({ api, onProgress, sleep: noSleep }, 'p1', 'kicad', {
      netlist: { fileName: 'main.net', content: '(export (version "E"))' },
      board: BOARD_FILE
    })

    expect(api.createSource).toHaveBeenCalledWith('p1', {
      type: 'kicad',
      name: 'main',
      config: { export: '(export (version "E"))', board: BOARD }
    })
    expect(states[0]).toEqual({
      phase: 'busy',
      stage: 'index',
      label: 'Reading main.net, power-board.kicad_pcb…',
      sourceId: undefined
    })
    expect(states[1]).toMatchObject({ label: 'Parsing netlist and board & building the graph…' })
  })

  it('labels a netlist-only run as parsing the netlist', async () => {
    const { states, onProgress } = collect()
    await runEdaConnect({ api: stubApi(), onProgress, sleep: noSleep }, 'p1', 'kicad', {
      netlist: XML_FILE
    })
    expect(states[1]).toMatchObject({ label: 'Parsing netlist & building the graph…' })
  })

  it('falls back to the provider id when the file name has no stem', async () => {
    const api = stubApi()
    await runEdaConnect({ api, onProgress: collect().onProgress, sleep: noSleep }, 'p1', 'kicad', {
      netlist: { fileName: '.xml', content: NETLIST }
    })
    expect(vi.mocked(api.createSource).mock.calls[0][1].name).toBe('kicad')
  })

  it('surfaces the backend sync error message verbatim when the sync fails', async () => {
    const message = 'kicad: export_format_unsupported — the file is a schematic.'
    const api = stubApi({
      getJob: vi.fn(async () => ({
        id: 'j1',
        project_id: 'p1',
        status: 'failed' as const,
        error: { message }
      })),
      getSyncs: vi.fn(async () => [sync({ status: 'succeeded' })])
    })
    const { states, onProgress } = collect()

    const result = await runEdaConnect({ api, onProgress, sleep: noSleep }, 'p1', 'kicad', {
      netlist: { fileName: 'board.net', content: '(export (version "E"))' }
    })

    expect(result.ok).toBe(false)
    expect(result.error).toContain('export_format_unsupported')
    expect(states[states.length - 1]).toEqual({ phase: 'error', error: message, sourceId: 's1' })
  })
}

function registerExportBoundsTests(): void {
  it('refuses a pick with neither netlist nor board without calling the API', async () => {
    const api = stubApi()
    const { states, onProgress } = collect()

    const result = await runEdaConnect({ api, onProgress, sleep: noSleep }, 'p1', 'kicad', {})

    expect(result).toEqual({ ok: false, error: NO_FILES_ERROR })
    expect(api.createSource).not.toHaveBeenCalled()
    expect(states).toEqual([{ phase: 'error', error: NO_FILES_ERROR }])
  })

  it('refuses an empty board even when the netlist is fine', async () => {
    const api = stubApi()
    const result = await runEdaConnect(
      { api, onProgress: collect().onProgress, sleep: noSleep },
      'p1',
      'kicad',
      { netlist: XML_FILE, board: { fileName: 'b.kicad_pcb', content: '   ' } }
    )
    expect(result).toEqual({ ok: false, error: EMPTY_EXPORT_ERROR })
    expect(api.createSource).not.toHaveBeenCalled()
  })

  it('refuses an oversized board even when the netlist is fine (per-file bound)', async () => {
    const api = stubApi()
    const result = await runEdaConnect(
      { api, onProgress: collect().onProgress, sleep: noSleep },
      'p1',
      'kicad',
      {
        netlist: XML_FILE,
        board: { fileName: 'b.kicad_pcb', content: 'x'.repeat(MAX_EXPORT_BYTES + 1) }
      }
    )
    expect(result).toEqual({ ok: false, error: OVERSIZE_EXPORT_ERROR })
    expect(api.createSource).not.toHaveBeenCalled()
  })

  it('refuses an empty file without calling the API', async () => {
    const api = stubApi()
    const { states, onProgress } = collect()

    const result = await runEdaConnect({ api, onProgress, sleep: noSleep }, 'p1', 'kicad', {
      netlist: { fileName: 'empty.xml', content: '' }
    })

    expect(result.ok).toBe(false)
    expect(api.createSource).not.toHaveBeenCalled()
    expect(states[states.length - 1].phase).toBe('error')
  })

  it('refuses an oversized export without calling the API (backend bound mirrored)', async () => {
    const api = stubApi()
    const { onProgress } = collect()

    const result = await runEdaConnect({ api, onProgress, sleep: noSleep }, 'p1', 'kicad', {
      netlist: { fileName: 'huge.xml', content: 'x'.repeat(MAX_EXPORT_BYTES + 1) }
    })

    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/too large/i)
    expect(api.createSource).not.toHaveBeenCalled()
  })
}

function registerExportSyncFailuresTests(): void {
  it('a sync still running when polling ends finishes as connected, indexing in the background', async () => {
    const api = stubApi({
      getJob: vi.fn(async () => ({
        id: 'j1',
        project_id: 'p1',
        status: 'running' as const,
        error: null
      }))
    })
    const { onProgress } = collect()

    const result = await runEdaConnect({ api, onProgress, sleep: noSleep }, 'p1', 'kicad', {
      netlist: XML_FILE
    })

    expect(result.ok).toBe(true)
    expect(result.result).toMatch(/still indexing in the background/i)
  })

  it('resolves to an error instead of throwing when the API rejects', async () => {
    const api = stubApi({
      createSource: vi.fn(async () => {
        throw new Error("No connector for 'kicad'")
      })
    })
    const { states, onProgress } = collect()

    const result = await runEdaConnect({ api, onProgress, sleep: noSleep }, 'p1', 'kicad', {
      netlist: XML_FILE
    })

    expect(result.ok).toBe(false)
    expect(result.error).toContain("No connector for 'kicad'")
    expect(states[states.length - 1].phase).toBe('error')
  })
}
