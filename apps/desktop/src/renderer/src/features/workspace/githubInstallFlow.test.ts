// SOLUSDEV-216 T9: the link flow's orchestration and every outcome.
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../lib/api/envelope.types'
import type { TeamInstallation } from '../../lib/api/resources.teamGithub'
import { runGithubInstall, type InstallFlowDeps } from './githubInstallFlow'

const INSTALLATION = { id: 'i1', account_login: 'fsae-ev' } as TeamInstallation

function makeDeps(overrides: Partial<InstallFlowDeps> = {}): InstallFlowDeps {
  return {
    start: vi.fn(async () => ({
      install_url: 'https://github.com/apps/solus/installations/new?state=s1',
      state: 's1',
      redirect_uri: 'http://127.0.0.1:1/cb'
    })),
    complete: vi.fn(async () => ({ kind: 'linked' as const, installation: INSTALLATION })),
    bridge: {
      getConnectorRedirectUrl: vi.fn(async () => 'http://127.0.0.1:1/cb'),
      awaitOAuth: vi.fn(async () => ({
        code: 'c1',
        installationId: 42,
        setupAction: 'install' as const
      }))
    },
    ...overrides
  }
}

const apiError = (code: string, status = 409): ApiError =>
  new ApiError(status, code, 'server says no')

describe('runGithubInstall', () => {
  it('starts, opens the install URL with the install wait, then completes', async () => {
    const deps = makeDeps()
    const outcome = await runGithubInstall(deps, 't1')
    expect(deps.start).toHaveBeenCalledWith('t1', 'http://127.0.0.1:1/cb')
    expect(deps.bridge?.awaitOAuth).toHaveBeenCalledWith(
      'https://github.com/apps/solus/installations/new?state=s1',
      's1',
      { install: true }
    )
    expect(deps.complete).toHaveBeenCalledWith('t1', {
      state: 's1',
      code: 'c1',
      installation_id: 42,
      setup_action: 'install'
    })
    expect(outcome).toEqual({ kind: 'linked', installation: INSTALLATION })
  })

  it('reports requested when a non-owner asked an org owner to approve', async () => {
    const deps = makeDeps({
      bridge: {
        getConnectorRedirectUrl: async () => 'r',
        awaitOAuth: async () => ({ code: 'c1', setupAction: 'request' as const })
      },
      complete: vi.fn(async () => ({ kind: 'requested' as const }))
    })
    expect(await runGithubInstall(deps, 't1')).toEqual({ kind: 'requested' })
    expect(deps.complete).toHaveBeenCalledWith('t1', {
      state: 's1',
      code: 'c1',
      setup_action: 'request'
    })
  })

  it('is cancelled when the loopback returns no code', async () => {
    const deps = makeDeps({
      bridge: { getConnectorRedirectUrl: async () => 'r', awaitOAuth: async () => ({}) }
    })
    expect(await runGithubInstall(deps, 't1')).toEqual({ kind: 'cancelled' })
    expect(deps.complete).not.toHaveBeenCalled()
  })

  it('fails with the loopback error and never completes', async () => {
    const deps = makeDeps({
      bridge: {
        getConnectorRedirectUrl: async () => 'r',
        awaitOAuth: async () => ({ error: 'A sign-in is already in progress.' })
      }
    })
    expect(await runGithubInstall(deps, 't1')).toEqual({
      kind: 'failed',
      reason: 'loopback',
      message: 'A sign-in is already in progress.'
    })
    expect(deps.complete).not.toHaveBeenCalled()
  })

  it('fails honestly outside the desktop app', async () => {
    const outcome = await runGithubInstall(makeDeps({ bridge: null }), 't1')
    expect(outcome).toEqual({ kind: 'failed', message: null, reason: 'no_bridge' })
  })

  it('names a refusal from install/start', async () => {
    const deps = makeDeps({
      start: vi.fn(async () => {
        throw apiError('already_linked')
      })
    })
    expect(await runGithubInstall(deps, 't1')).toEqual({
      kind: 'refused',
      code: 'already_linked',
      limit: null
    })
  })

  it('names a refusal from install/complete', async () => {
    const deps = makeDeps({
      complete: vi.fn(async () => {
        throw apiError('installation_linked_elsewhere')
      })
    })
    const outcome = await runGithubInstall(deps, 't1')
    expect(outcome).toMatchObject({ kind: 'refused', code: 'installation_linked_elsewhere' })
  })

  it('carries the plan limit block on plan_limit_reached', async () => {
    const deps = makeDeps({
      complete: vi.fn(async () => {
        throw new ApiError(409, 'plan_limit_reached', 'Plan allows 1 integration', [
          { limit: 'max_integrations', current: 1, max: 1 }
        ])
      })
    })
    const outcome = await runGithubInstall(deps, 't1')
    expect(outcome).toMatchObject({
      kind: 'refused',
      code: 'plan_limit_reached',
      limit: { max: 1, message: 'Plan allows 1 integration' }
    })
  })

  it('fails on an unknown error without leaking its message', async () => {
    const deps = makeDeps({
      complete: vi.fn(async () => {
        throw new Error('boom')
      })
    })
    expect(await runGithubInstall(deps, 't1')).toEqual({
      kind: 'failed',
      message: null,
      reason: 'error'
    })
  })
})
