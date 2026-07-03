import { describe, it, expect, vi } from 'vitest'
import { runGithubConnect, type GithubConnectApi, type GithubConnectDeps } from './githubConnect'
import type { GithubRepo, Source, Sync } from '../../lib/api/resources'
import type { OAuthBridge } from '../auth/githubOAuth'
import type { ConnectionState } from './onboardingStore'

const REPO: GithubRepo = { full_name: 'strider/strider-fw', default_branch: 'main', private: false }

function source(overrides: Partial<Source> = {}): Source {
  return {
    id: 's1',
    project_id: 'p1',
    type: 'github',
    name: 'GitHub',
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

/** A fully-stubbed happy-path API; individual tests override single methods. */
function stubApi(overrides: Partial<GithubConnectApi> = {}): GithubConnectApi {
  return {
    startGithubOAuth: vi.fn(async () => ({
      authorize_url: 'https://github.com/login/oauth/authorize?x=1',
      state: 'st',
      source_id: 's1'
    })),
    exchangeGithubOAuth: vi.fn(async () => source()),
    listRepos: vi.fn(async () => [REPO]),
    updateSource: vi.fn(async () => source()),
    triggerSync: vi.fn(async () => ({ job_id: 'j1', status: 'queued' })),
    getSyncs: vi.fn(async () => [sync()]),
    getSource: vi.fn(async () => source({ entity_count: 214 })),
    ...overrides
  }
}

function stubBridge(callback: { code?: string; error?: string }): OAuthBridge {
  return {
    getRedirectUrl: vi.fn(async () => 'http://127.0.0.1:7421/cb'),
    awaitGithub: vi.fn(async () => callback)
  }
}

function makeDeps(
  api: GithubConnectApi,
  bridge: OAuthBridge | null,
  chooseRepo: (repos: GithubRepo[]) => Promise<GithubRepo | null> = async (r) => r[0]
): { deps: GithubConnectDeps; states: ConnectionState[] } {
  const states: ConnectionState[] = []
  const deps: GithubConnectDeps = {
    api,
    bridge,
    onProgress: (s) => states.push(s),
    onChooseRepo: chooseRepo,
    sleep: async () => undefined
  }
  return { deps, states }
}

const OPTS = { redirectUri: 'http://127.0.0.1:7421/cb' }

describe('runGithubConnect', () => {
  it('drives oauth → exchange → repo → sync → done on the happy path', async () => {
    const api = stubApi()
    const { deps, states } = makeDeps(api, stubBridge({ code: 'cd' }))

    const result = await runGithubConnect(deps, 'p1', OPTS)

    expect(result.ok).toBe(true)
    expect(result.sourceId).toBe('s1')
    expect(result.result).toBe('Connected — 214 entities indexed')
    expect(api.startGithubOAuth).toHaveBeenCalledWith('p1', {
      redirect_uri: 'http://127.0.0.1:7421/cb',
      repo: undefined
    })
    expect(api.updateSource).toHaveBeenCalledWith('p1', 's1', {
      config: { repo: 'strider/strider-fw', branch: 'main' }
    })
    expect(api.triggerSync).toHaveBeenCalledWith('p1', 's1')
    // The final reported state is done.
    expect(states[states.length - 1]).toEqual({
      phase: 'done',
      sourceId: 's1',
      result: 'Connected — 214 entities indexed'
    })
  })

  it('falls back with an error when the Electron bridge is absent', async () => {
    const api = stubApi()
    const { deps, states } = makeDeps(api, null)

    const result = await runGithubConnect(deps, 'p1', OPTS)

    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/desktop app/i)
    expect(api.startGithubOAuth).not.toHaveBeenCalled()
    expect(states[states.length - 1].phase).toBe('error')
  })

  it('marks an error when the OAuth callback returns an error', async () => {
    const api = stubApi()
    const { deps, states } = makeDeps(api, stubBridge({ error: 'access_denied' }))

    const result = await runGithubConnect(deps, 'p1', OPTS)

    expect(result.ok).toBe(false)
    expect(result.error).toBe('access_denied')
    expect(api.exchangeGithubOAuth).not.toHaveBeenCalled()
    expect(states[states.length - 1]).toMatchObject({ phase: 'error', error: 'access_denied' })
  })

  it('marks an error when the callback has no code (cancelled)', async () => {
    const api = stubApi()
    const { deps } = makeDeps(api, stubBridge({}))
    const result = await runGithubConnect(deps, 'p1', OPTS)
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/cancelled/i)
  })

  it('reports the sync error when the sync fails', async () => {
    const api = stubApi({
      getSyncs: vi.fn(async () => [sync({ status: 'failed', errors: ['rate limited'] })])
    })
    const { deps, states } = makeDeps(api, stubBridge({ code: 'cd' }))

    const result = await runGithubConnect(deps, 'p1', OPTS)

    expect(result.ok).toBe(false)
    expect(result.error).toBe('rate limited')
    expect(api.getSource).not.toHaveBeenCalled()
    expect(states[states.length - 1]).toMatchObject({ phase: 'error', error: 'rate limited' })
  })

  it('surfaces a repo picker when multiple repos are returned', async () => {
    const repos: GithubRepo[] = [
      REPO,
      { full_name: 'strider/strider-tools', default_branch: 'dev', private: true }
    ]
    const api = stubApi({ listRepos: vi.fn(async () => repos) })
    const chooseRepo = vi.fn(async () => repos[1])
    const { deps, states } = makeDeps(api, stubBridge({ code: 'cd' }), chooseRepo)

    const result = await runGithubConnect(deps, 'p1', OPTS)

    expect(chooseRepo).toHaveBeenCalledWith(repos)
    // The picker state carried the repos for the UI to render.
    expect(states.some((s) => s.phase === 'busy' && s.repos?.length === 2)).toBe(true)
    expect(api.updateSource).toHaveBeenCalledWith('p1', 's1', {
      config: { repo: 'strider/strider-tools', branch: 'dev' }
    })
    expect(result.ok).toBe(true)
  })

  it('skips the picker entirely when a repo is preselected', async () => {
    const api = stubApi()
    const chooseRepo = vi.fn(async () => null)
    const { deps } = makeDeps(api, stubBridge({ code: 'cd' }), chooseRepo)

    const result = await runGithubConnect(deps, 'p1', { ...OPTS, preselectedRepo: REPO })

    expect(chooseRepo).not.toHaveBeenCalled()
    expect(api.listRepos).not.toHaveBeenCalled()
    expect(api.startGithubOAuth).toHaveBeenCalledWith('p1', {
      redirect_uri: OPTS.redirectUri,
      repo: 'strider/strider-fw'
    })
    expect(result.ok).toBe(true)
  })

  it('errors when the user cancels the repo picker', async () => {
    const repos: GithubRepo[] = [
      REPO,
      { full_name: 'strider/x', default_branch: 'main', private: false }
    ]
    const api = stubApi({ listRepos: vi.fn(async () => repos) })
    const { deps } = makeDeps(api, stubBridge({ code: 'cd' }), async () => null)
    const result = await runGithubConnect(deps, 'p1', OPTS)
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/no repository/i)
    expect(api.triggerSync).not.toHaveBeenCalled()
  })

  it('errors and reports when an API call throws mid-flow', async () => {
    const api = stubApi({
      exchangeGithubOAuth: vi.fn(async () => {
        throw new Error('exchange 500')
      })
    })
    const { deps, states } = makeDeps(api, stubBridge({ code: 'cd' }))
    const result = await runGithubConnect(deps, 'p1', OPTS)
    expect(result.ok).toBe(false)
    expect(result.error).toBe('exchange 500')
    expect(states[states.length - 1]).toMatchObject({ phase: 'error', error: 'exchange 500' })
  })

  it('times out when the sync never reaches a terminal state', async () => {
    const api = stubApi({ getSyncs: vi.fn(async () => [sync({ status: 'running' })]) })
    const { deps } = makeDeps(api, stubBridge({ code: 'cd' }))
    const result = await runGithubConnect(deps, 'p1', OPTS)
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/timed out/i)
  })

  it('falls back to entities_created when the source omits entity_count', async () => {
    const api = stubApi({ getSource: vi.fn(async () => source()) })
    const { deps } = makeDeps(api, stubBridge({ code: 'cd' }))
    const result = await runGithubConnect(deps, 'p1', OPTS)
    expect(result.result).toBe('Connected — 214 entities indexed')
  })
})
