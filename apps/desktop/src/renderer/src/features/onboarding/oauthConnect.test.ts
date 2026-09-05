// The provider-agnostic OAuth spine. These cases used to live in
// githubConnect.test.ts against the GitHub-only flow; they are the same
// guarantees, now asserted for an arbitrary provider. The provider used here is
// deliberately FICTIONAL — if any of this passes only for github/onshape, the
// generalisation has a hardcode in it.
import { describe, it, expect, vi } from 'vitest'
import {
  runOAuthConnect,
  type ConfigureStep,
  type OAuthConnectApi,
  type OAuthConnectDeps
} from './oauthConnect'
import type { Connection, Source, Sync } from '../../lib/api/resources'
import type { OAuthBridge } from '../auth/githubOAuth'
import type { ConnectionState } from './onboardingStore'

const PROVIDER = 'someFutureCad'

function source(overrides: Partial<Source> = {}): Source {
  return {
    id: 's1',
    project_id: 'p1',
    type: 'github',
    name: 'Source',
    status: 'connected',
    config: {},
    account_login: 'maya',
    last_synced_at: null,
    last_error: null,
    created_at: '',
    updated_at: '',
    ...overrides
  }
}

function connection(): Connection {
  return {
    id: 'c1',
    provider: PROVIDER,
    status: 'connected',
    account_login: 'maya',
    access: null,
    last_error: null,
    projects: [],
    created_at: '',
    updated_at: ''
  }
}

function sync(overrides: Partial<Sync> = {}): Sync {
  return {
    id: 'sy1',
    status: 'succeeded',
    entities_created: 214,
    relations_created: 31,
    errors: [],
    ...overrides
  }
}

function stubApi(overrides: Partial<OAuthConnectApi> = {}): OAuthConnectApi {
  return {
    startOAuth: vi.fn(async () => ({
      authorize_url: 'https://example.test/authorize?x=1',
      state: 'st',
      connection_id: 'c1',
      source_id: 's1'
    })),
    exchangeOAuth: vi.fn(async () => ({ connection: connection(), source: source() })),
    createSource: vi.fn(async () => source()),
    updateSource: vi.fn(async () => source()),
    triggerSync: vi.fn(async () => ({ job_id: 'j1', status: 'queued' })),
    getSyncs: vi.fn(async () => [sync()]),
    getSource: vi.fn(async () => source({ entity_count: 214 })),
    ...overrides
  }
}

function stubBridge(callback: { code?: string; error?: string }): OAuthBridge {
  return {
    getRedirectUrl: vi.fn(async () => 'http://127.0.0.1:7421/cb?solus_cb=x'),
    awaitGithub: vi.fn(async () => callback),
    getConnectorRedirectUrl: vi.fn(async () => 'http://127.0.0.1:7421/cb'),
    awaitOAuth: vi.fn(async () => callback)
  }
}

const CONFIGURE: ConfigureStep = async () => ({
  config: { document_id: 'd1' },
  label: 'Widget assembly'
})

function makeDeps(
  api: OAuthConnectApi,
  bridge: OAuthBridge | null,
  configure: ConfigureStep = CONFIGURE
): { deps: OAuthConnectDeps; states: ConnectionState[] } {
  const states: ConnectionState[] = []
  return {
    deps: {
      api,
      bridge,
      onProgress: (s) => states.push(s),
      configure,
      sleep: async () => undefined
    },
    states
  }
}

const OPTS = { redirectUri: 'http://127.0.0.1:7421/cb', displayName: 'FutureCAD' }

describe('runOAuthConnect', () => {
  it('drives oauth → exchange → configure → sync → done on the happy path', async () => {
    const api = stubApi()
    const { deps, states } = makeDeps(api, stubBridge({ code: 'cd' }))

    const result = await runOAuthConnect(deps, 'p1', PROVIDER, OPTS)

    expect(result.ok).toBe(true)
    expect(result.sourceId).toBe('s1')
    expect(result.result).toBe('Connected — 214 entities indexed')
    expect(api.updateSource).toHaveBeenCalledWith('p1', 's1', {
      config: { document_id: 'd1' }
    })
    expect(api.triggerSync).toHaveBeenCalledWith('p1', 's1')
    expect(states[states.length - 1]).toEqual({
      phase: 'done',
      sourceId: 's1',
      result: 'Connected — 214 entities indexed'
    })
  })

  // The whole point of the refactor: the provider must reach the API, not be
  // baked into the module.
  it('passes the provider through to start, exchange, and the configure step', async () => {
    const api = stubApi()
    const configure = vi.fn<ConfigureStep>(async () => ({ config: { a: 1 } }))
    const { deps } = makeDeps(api, stubBridge({ code: 'cd' }), configure)

    await runOAuthConnect(deps, 'p1', PROVIDER, OPTS)

    expect(api.startOAuth).toHaveBeenCalledWith('p1', PROVIDER, {
      redirect_uri: 'http://127.0.0.1:7421/cb'
    })
    expect(api.exchangeOAuth).toHaveBeenCalledWith(PROVIDER, { state: 'st', code: 'cd' })
    expect(configure).toHaveBeenCalledWith({
      projectId: 'p1',
      sourceId: 's1',
      provider: PROVIDER
    })
  })

  it('emits machine-readable stages so the wizard step rail never parses labels', async () => {
    const { deps, states } = makeDeps(stubApi(), stubBridge({ code: 'cd' }))
    await runOAuthConnect(deps, 'p1', PROVIDER, OPTS)
    const stages = states.map((s) => (s.phase === 'busy' ? s.stage : undefined))
    expect(stages).toEqual(['authorize', 'link', 'index', undefined])
  })

  it('names the provider in its progress copy rather than a hardcoded vendor', async () => {
    const { deps, states } = makeDeps(stubApi(), stubBridge({ code: 'cd' }))
    await runOAuthConnect(deps, 'p1', PROVIDER, OPTS)
    const labels = states.map((s) => (s.phase === 'busy' ? s.label : '')).join(' ')
    expect(labels).toContain('Authorizing with FutureCAD…')
    expect(labels).toContain('Linking your FutureCAD account…')
    expect(labels).not.toMatch(/github/i)
  })

  it('falls back with an error when the Electron bridge is absent', async () => {
    const api = stubApi()
    const { deps, states } = makeDeps(api, null)

    const result = await runOAuthConnect(deps, 'p1', PROVIDER, OPTS)

    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/desktop app/i)
    expect(api.startOAuth).not.toHaveBeenCalled()
    expect(states[states.length - 1].phase).toBe('error')
  })

  it('reuses a linked account: binds the project and skips the handshake (SOLUSDEV-241)', async () => {
    const api = stubApi()
    const bridge = stubBridge({ code: 'cd' })
    const { deps, states } = makeDeps(api, bridge)
    const chooseAccess = vi.fn(async () => ({ access: 'write' }))

    const result = await runOAuthConnect({ ...deps, chooseAccess }, 'p1', PROVIDER, {
      redirectUri: 'http://127.0.0.1:7421/cb',
      displayName: 'Future CAD',
      linkedConnection: { id: 'c1', login: 'maya' }
    })

    expect(result.ok).toBe(true)
    expect(api.createSource).toHaveBeenCalledWith('p1', {
      type: PROVIDER,
      name: 'Future CAD',
      connection_id: 'c1'
    })
    // No grant asked for, no browser opened, no code exchanged.
    expect(chooseAccess).not.toHaveBeenCalled()
    expect(api.startOAuth).not.toHaveBeenCalled()
    expect(bridge.awaitOAuth).not.toHaveBeenCalled()
    expect(api.exchangeOAuth).not.toHaveBeenCalled()
    // …but the picker and the sync still run.
    expect(api.updateSource).toHaveBeenCalledWith('p1', 's1', { config: { document_id: 'd1' } })
    expect(api.triggerSync).toHaveBeenCalledWith('p1', 's1')
    expect(states[0]).toEqual({
      phase: 'busy',
      stage: 'link',
      label: 'Using your linked Future CAD account…',
      sourceId: undefined
    })
  })

  it('reports an exchange that linked the account but attached no source', async () => {
    const api = stubApi({
      exchangeOAuth: vi.fn(async () => ({ connection: connection(), source: null }))
    })
    const { deps } = makeDeps(api, stubBridge({ code: 'cd' }))
    const result = await runOAuthConnect(deps, 'p1', PROVIDER, {
      redirectUri: 'u',
      displayName: 'Future CAD'
    })
    expect(result.ok).toBe(false)
    expect(result.error).toBe('Future CAD was linked to your account but not to this project.')
    expect(api.triggerSync).not.toHaveBeenCalled()
  })

  it('marks an error when the OAuth callback returns an error', async () => {
    const api = stubApi()
    const { deps, states } = makeDeps(api, stubBridge({ error: 'access_denied' }))

    const result = await runOAuthConnect(deps, 'p1', PROVIDER, OPTS)

    expect(result.ok).toBe(false)
    expect(result.error).toBe('access_denied')
    expect(api.exchangeOAuth).not.toHaveBeenCalled()
    expect(states[states.length - 1]).toMatchObject({ phase: 'error', error: 'access_denied' })
  })

  it('marks an error when the callback has no code (cancelled)', async () => {
    const { deps } = makeDeps(stubApi(), stubBridge({}))
    const result = await runOAuthConnect(deps, 'p1', PROVIDER, OPTS)
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/cancelled/i)
  })

  it('surfaces the configure step’s own error and never syncs', async () => {
    const api = stubApi()
    const { deps, states } = makeDeps(api, stubBridge({ code: 'cd' }), async () => ({
      error: 'No repository selected.'
    }))

    const result = await runOAuthConnect(deps, 'p1', PROVIDER, OPTS)

    expect(result.ok).toBe(false)
    expect(result.error).toBe('No repository selected.')
    expect(result.sourceId).toBe('s1')
    expect(api.updateSource).not.toHaveBeenCalled()
    expect(api.triggerSync).not.toHaveBeenCalled()
    expect(states[states.length - 1]).toMatchObject({ phase: 'error' })
  })

  it('reports the sync error when the sync fails', async () => {
    const api = stubApi({
      getSyncs: vi.fn(async () => [sync({ status: 'failed', errors: ['rate limited'] })])
    })
    const { deps, states } = makeDeps(api, stubBridge({ code: 'cd' }))

    const result = await runOAuthConnect(deps, 'p1', PROVIDER, OPTS)

    expect(result.ok).toBe(false)
    expect(result.error).toBe('rate limited')
    expect(api.getSource).not.toHaveBeenCalled()
    expect(states[states.length - 1]).toMatchObject({ phase: 'error', error: 'rate limited' })
  })

  it('errors and reports when an API call throws mid-flow', async () => {
    const api = stubApi({
      exchangeOAuth: vi.fn(async () => {
        throw new Error('exchange 500')
      })
    })
    const { deps, states } = makeDeps(api, stubBridge({ code: 'cd' }))
    const result = await runOAuthConnect(deps, 'p1', PROVIDER, OPTS)
    expect(result.ok).toBe(false)
    expect(result.error).toBe('exchange 500')
    expect(states[states.length - 1]).toMatchObject({ phase: 'error', error: 'exchange 500' })
  })

  it('times out when the sync never reaches a terminal state', async () => {
    const api = stubApi({ getSyncs: vi.fn(async () => [sync({ status: 'running' })]) })
    const { deps } = makeDeps(api, stubBridge({ code: 'cd' }))
    const result = await runOAuthConnect(deps, 'p1', PROVIDER, OPTS)
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/timed out/i)
  })

  it('falls back to entities_created when the source omits entity_count', async () => {
    const api = stubApi({ getSource: vi.fn(async () => source()) })
    const { deps } = makeDeps(api, stubBridge({ code: 'cd' }))
    const result = await runOAuthConnect(deps, 'p1', PROVIDER, OPTS)
    expect(result.result).toBe('Connected — 214 entities indexed')
  })

  it('falls back to the provider id when no display name is given', async () => {
    const { deps, states } = makeDeps(stubApi(), null)
    await runOAuthConnect(deps, 'p1', PROVIDER, { redirectUri: '' })
    expect(states[0]).toMatchObject({
      phase: 'error',
      error: `${PROVIDER} connect needs the desktop app.`
    })
  })
})
