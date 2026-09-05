// The account-scoped engine (SOLUSDEV-241): grant choice → handshake →
// exchange → done, with no project, no picker and no sync. Provider-agnostic —
// the provider here is fictional on purpose.
import { describe, it, expect, vi } from 'vitest'
import { runAccountConnect, type AccountConnectApi } from './accountConnect'
import type { Connection } from '../../lib/api/resources'
import type { OAuthBridge } from '../auth/githubOAuth'
import type { ConnectionState } from './onboardingStore'

const PROVIDER = 'someFutureCad'

function connection(overrides: Partial<Connection> = {}): Connection {
  return {
    id: 'c1',
    provider: PROVIDER,
    status: 'connected',
    account_login: 'maya',
    access: 'read',
    needs_reauth: null,
    last_error: null,
    projects: [],
    created_at: '',
    updated_at: '',
    ...overrides
  }
}

function stubApi(overrides: Partial<AccountConnectApi> = {}): AccountConnectApi {
  return {
    startOAuth: vi.fn(async () => ({
      authorize_url: 'https://example.test/authorize',
      state: 'st',
      connection_id: 'c1',
      source_id: null
    })),
    exchangeOAuth: vi.fn(async () => ({ connection: connection() })),
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

describe('runAccountConnect', () => {
  it('binds the account with NO project and reports who it connected as', async () => {
    const api = stubApi()
    const progress: ConnectionState[] = []
    const result = await runAccountConnect(
      { api, bridge: stubBridge({ code: 'cd' }), onProgress: (s) => progress.push(s) },
      PROVIDER,
      { redirectUri: 'http://127.0.0.1:7421/cb', displayName: 'Future CAD' }
    )

    expect(result).toEqual({
      ok: true,
      connectionId: 'c1',
      login: 'maya',
      result: 'Connected as maya'
    })
    expect(api.startOAuth).toHaveBeenCalledWith(null, PROVIDER, {
      redirect_uri: 'http://127.0.0.1:7421/cb'
    })
    expect(api.exchangeOAuth).toHaveBeenCalledWith(PROVIDER, { state: 'st', code: 'cd' })
    expect(progress.map((s) => (s.phase === 'busy' ? s.stage : s.phase))).toEqual([
      'authorize',
      'link',
      'done'
    ])
  })

  it('sends the chosen grant in the start request', async () => {
    const api = stubApi()
    await runAccountConnect(
      {
        api,
        bridge: stubBridge({ code: 'cd' }),
        onProgress: () => undefined,
        chooseAccess: async () => ({ access: 'write' })
      },
      PROVIDER,
      { redirectUri: 'http://127.0.0.1:7421/cb' }
    )
    expect(api.startOAuth).toHaveBeenCalledWith(null, PROVIDER, {
      redirect_uri: 'http://127.0.0.1:7421/cb',
      access: 'write'
    })
  })

  it('names the opaque account when the provider gave no login', async () => {
    const api = stubApi({
      exchangeOAuth: vi.fn(async () => ({ connection: connection({ account_login: null }) }))
    })
    const result = await runAccountConnect(
      { api, bridge: stubBridge({ code: 'cd' }), onProgress: () => undefined },
      PROVIDER,
      { redirectUri: 'u', displayName: 'Future CAD' }
    )
    expect(result.result).toBe('Future CAD account connected')
  })

  it('reports a cancelled handshake honestly and never exchanges', async () => {
    const api = stubApi()
    const result = await runAccountConnect(
      { api, bridge: stubBridge({}), onProgress: () => undefined },
      PROVIDER,
      { redirectUri: 'u', displayName: 'Future CAD' }
    )
    expect(result).toEqual({ ok: false, error: 'Future CAD sign-in was cancelled.' })
    expect(api.exchangeOAuth).not.toHaveBeenCalled()
  })

  it('needs the desktop bridge', async () => {
    const api = stubApi()
    const result = await runAccountConnect(
      { api, bridge: null, onProgress: () => undefined },
      PROVIDER,
      { redirectUri: 'u', displayName: 'Future CAD' }
    )
    expect(result.ok).toBe(false)
    expect(result.error).toBe('Future CAD connect needs the desktop app.')
    expect(api.startOAuth).not.toHaveBeenCalled()
  })

  it('never throws: an exchange failure becomes an error result', async () => {
    const api = stubApi({
      exchangeOAuth: vi.fn(async () => {
        throw new Error('exchange exploded')
      })
    })
    const progress: ConnectionState[] = []
    const result = await runAccountConnect(
      { api, bridge: stubBridge({ code: 'cd' }), onProgress: (s) => progress.push(s) },
      PROVIDER,
      { redirectUri: 'u' }
    )
    expect(result).toEqual({ ok: false, error: 'exchange exploded' })
    expect(progress.at(-1)).toEqual({ phase: 'error', error: 'exchange exploded' })
  })
})
