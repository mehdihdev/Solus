// SOLUSDEV-250 (I3) — the Code environment route (docs/api/code-environment.md
// §2): exact path and query, and the widening of a partial answer to the full
// view so callers never branch on absent fields.
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './client'
import type { Source } from './resources'
import {
  EMPTY_CODE_ENVIRONMENT_VIEW,
  getCodeEnvironment,
  type CodeEnvironmentView
} from './resources.codeenv'

function stubClient(result: unknown): { client: ApiClient; calls: { path: string }[] } {
  const calls: { path: string }[] = []
  const client: ApiClient = {
    request: vi.fn(async (path: string) => {
      calls.push({ path })
      return result as never
    }),
    requestPage: vi.fn(async () => {
      throw new Error('unused')
    })
  }
  return { client, calls }
}

const MACHINE_ID = '0123456789abcdef0123456789abcdef'

const SOURCE: Source = {
  id: 's1',
  project_id: 'p1',
  type: 'local',
  name: 'mehdi-mbp',
  status: 'connected',
  config: { machine_id: MACHINE_ID, machine_name: 'mehdi-mbp', folder_name: 'rover-fw' },
  account_login: null,
  last_synced_at: null,
  last_error: null,
  created_at: '',
  updated_at: ''
}

const FULL: CodeEnvironmentView = {
  source: SOURCE,
  bridge: { connected: true, code_server: true },
  probe: {
    python: { path: '/usr/bin/python3', version: '3.12.4' },
    interpreters: [{ path: '/usr/bin/python3', version: '3.12.4' }],
    venv: {
      path: '.venv',
      python_version: '3.12.4',
      packages: [{ name: 'torch', version: '2.1.0' }],
      truncated: false
    },
    conda: null,
    uv: { path: '/opt/homebrew/bin/uv', version: '0.4.0' }
  },
  requirements: { count: 3, files: ['isaac/requirements.txt', 'policy/pyproject.toml'] },
  conflicts: [
    {
      checker_id: 'pin_conflict',
      severity: 'warning',
      message: 'torch is pinned differently across files',
      evidence: {
        pins: [
          { specifier: '==2.1.0', source_file: 'isaac/requirements.txt' },
          { specifier: '>=2.3', source_file: 'policy/pyproject.toml' }
        ]
      },
      suggested_area: 'code'
    }
  ],
  proposal: {
    environments: [
      {
        name: 'isaac',
        source_files: ['isaac/requirements.txt'],
        requirements: [
          { name: 'torch', specifier: '==2.1.0', source_file: 'isaac/requirements.txt' }
        ]
      }
    ],
    split: true
  }
}

describe('getCodeEnvironment', () => {
  it('GETs the project route with the machine id as a query parameter, encoded', async () => {
    const { client, calls } = stubClient(FULL)

    const out = await getCodeEnvironment('p 1', 'm/1', client)

    expect(calls).toEqual([{ path: '/projects/p%201/code-environment?machine_id=m%2F1' }])
    expect(out).toEqual(FULL)
  })

  it('widens a bare {source: null} answer to the empty view', async () => {
    const { client } = stubClient({ source: null })

    const out = await getCodeEnvironment('p1', MACHINE_ID, client)

    expect(out).toEqual(EMPTY_CODE_ENVIRONMENT_VIEW)
    expect(out.bridge.connected).toBe(false)
    expect(out.probe).toBeNull()
    expect(out.conflicts).toEqual([])
  })

  it('keeps an offline bridge honest: probe null, graph-derived fields intact', async () => {
    const { client } = stubClient({
      source: SOURCE,
      bridge: { connected: false, code_server: false },
      probe: null,
      requirements: { count: 1, files: ['requirements.txt'] }
    })

    const out = await getCodeEnvironment('p1', MACHINE_ID, client)

    expect(out.source?.id).toBe('s1')
    expect(out.bridge).toEqual({ connected: false, code_server: false })
    expect(out.probe).toBeNull()
    expect(out.requirements).toEqual({ count: 1, files: ['requirements.txt'] })
    expect(out.proposal).toBeNull()
  })

  it('surfaces the request failure unchanged', async () => {
    const client: ApiClient = {
      request: vi.fn(async () => {
        throw new Error('down')
      }),
      requestPage: vi.fn(async () => {
        throw new Error('unused')
      })
    }
    await expect(getCodeEnvironment('p1', MACHINE_ID, client)).rejects.toThrow('down')
  })
})
