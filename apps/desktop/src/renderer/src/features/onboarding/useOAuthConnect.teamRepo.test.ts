// SOLUSDEV-216 / ADR-039: binding a project to a TEAM's GitHub installation.
// The real orchestration runs against a mocked API surface so the assertions
// are on what the wire sees: installation:true, no handshake, a rail without
// access/authorize, and named errors.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useOAuthConnect } from './useOAuthConnect'
import { useOnboardingStore, type ConnectionState } from './onboardingStore'
import { wizardSteps } from './connectSteps'
import { useSettingsStore } from '../../store/settingsStore'
import { ApiError } from '../../lib/api/envelope.types'
import * as bridgeModule from '../../lib/desktopBridge'
import * as resources from '../../lib/api/resources'
import type { SelectableItem } from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    createSource: vi.fn(),
    updateSource: vi.fn(),
    triggerSync: vi.fn(),
    getSyncs: vi.fn(),
    getJob: vi.fn(),
    getSource: vi.fn(),
    startOAuth: vi.fn(),
    exchangeOAuth: vi.fn(),
    listSelectable: vi.fn()
  }
})

const m = vi.mocked(resources)
const TEAM_REPO: SelectableItem = {
  id: 'fsae-ev/vcu',
  name: 'fsae-ev/vcu',
  config: { repo: 'fsae-ev/vcu', branch: 'main' }
}
const SELECTION = { mode: 'single', config_key: 'repo', label: 'repository' } as const
const awaitOAuth = vi.fn(async () => ({ code: 'cd' }))

function stubBridge(): void {
  vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue({
    getRedirectUrl: vi.fn(async () => ''),
    awaitGithub: vi.fn(),
    getConnectorRedirectUrl: vi.fn(async () => 'http://127.0.0.1:9/cb'),
    awaitOAuth,
    cancelOAuth: vi.fn(async () => true)
  })
}

function stubHappyApi(): void {
  m.createSource.mockResolvedValue({ id: 's1' } as resources.Source)
  m.updateSource.mockResolvedValue({ id: 's1' } as resources.Source)
  m.triggerSync.mockResolvedValue({ job_id: 'j1', status: 'queued' })
  m.getJob.mockResolvedValue({
    id: 'j1',
    project_id: 'p1',
    status: 'succeeded'
  } as resources.SyncJob)
  m.getSource.mockResolvedValue({ id: 's1', entity_count: 4 } as resources.Source)
  m.getSyncs.mockResolvedValue([])
}

function stages(): string[] {
  return recorded.flatMap((s) => (s.phase === 'busy' && s.stage ? [s.stage] : []))
}

const recorded: ConnectionState[] = []
let unsubscribe: () => void = () => undefined

beforeEach(() => {
  vi.clearAllMocks()
  recorded.length = 0
  useOnboardingStore.getState().reset()
  useSettingsStore.setState({ solMode: 'Guide' })
  unsubscribe = useOnboardingStore.subscribe((state) => {
    const c = state.connections.github
    if (c) recorded.push(c)
  })
  stubBridge()
  stubHappyApi()
})
afterEach(() => {
  unsubscribe()
  vi.restoreAllMocks()
})

async function startTeam(): Promise<resources.Source | unknown> {
  const { result } = renderHook(() => useOAuthConnect())
  let outcome: unknown
  await act(async () => {
    outcome = await result.current.start('p1', 'github', {
      displayName: 'GitHub',
      selection: SELECTION,
      teamRepo: TEAM_REPO
    })
  })
  return outcome
}

describe('useOAuthConnect — team repo bind', () => {
  it('creates the source through the installation with the picked repo, no handshake', async () => {
    const outcome = await startTeam()

    expect(outcome).toMatchObject({ ok: true, sourceId: 's1' })
    expect(m.createSource).toHaveBeenCalledWith('p1', {
      type: 'github',
      name: 'GitHub',
      installation: true,
      config: { repo: 'fsae-ev/vcu', branch: 'main' }
    })
    expect(m.startOAuth).not.toHaveBeenCalled()
    expect(m.exchangeOAuth).not.toHaveBeenCalled()
    expect(awaitOAuth).not.toHaveBeenCalled()
    expect(m.listSelectable).not.toHaveBeenCalled()
  })

  it('runs link then index with the chosen repo, and never an access/authorize stage', async () => {
    await startTeam()

    expect(stages()).toEqual(expect.arrayContaining(['link', 'index']))
    expect(stages()).not.toContain('access')
    expect(stages()).not.toContain('authorize')
    expect(m.updateSource).toHaveBeenCalledWith('p1', 's1', {
      config: { repo: 'fsae-ev/vcu', branch: 'main' }
    })
    expect(m.triggerSync).toHaveBeenCalledWith('p1', 's1')
  })

  it('names the team installation, not a linked account, in its progress copy', async () => {
    await startTeam()
    const link = recorded.find((s) => s.phase === 'busy' && s.stage === 'link')
    expect(link && 'label' in link ? link.label : '').toMatch(/organization/i)
  })

  it('the rail for the team path has no access or sign-in step', () => {
    const ids = wizardSteps({
      mode: 'oauth',
      accessModes: {
        default: 'read',
        modes: [
          { id: 'read', label: 'Read', description: '', scopes: [] },
          { id: 'write', label: 'Write', description: '', scopes: [] }
        ]
      },
      selection: SELECTION,
      configFields: [],
      linkedAccount: true
    }).map((s) => s.id)
    expect(ids).toEqual(['configure', 'index'])
  })

  it.each([
    ['installation_missing', 409],
    ['installation_suspended', 409],
    ['repo_not_in_installation', 400],
    ['credential_conflict', 400]
  ])('surfaces %s as a named error instead of the raw API text', async (code, status) => {
    m.createSource.mockRejectedValue(new ApiError(status, code, 'raw api text'))

    const outcome = (await startTeam()) as { ok: boolean; error?: string }

    expect(outcome.ok).toBe(false)
    expect(outcome.error).toBeTruthy()
    expect(outcome.error).not.toBe('raw api text')
    const last = recorded[recorded.length - 1]
    expect(last).toMatchObject({ phase: 'error', error: outcome.error })
    expect(m.updateSource).not.toHaveBeenCalled()
  })

  it('gives the terse Expert variant', async () => {
    m.createSource.mockRejectedValue(new ApiError(409, 'installation_suspended', 'x'))
    const guide = ((await startTeam()) as { error: string }).error
    useSettingsStore.setState({ solMode: 'Expert' })
    m.createSource.mockRejectedValue(new ApiError(409, 'installation_suspended', 'x'))
    const expert = ((await startTeam()) as { error: string }).error
    expect(expert.length).toBeLessThan(guide.length)
  })

  it('shows an unrelated failure with its own message', async () => {
    m.createSource.mockRejectedValue(new Error('network down'))
    const outcome = (await startTeam()) as { error: string }
    expect(outcome.error).toBe('network down')
  })
})

describe('useOAuthConnect — account path is unchanged', () => {
  it('without a teamRepo, a linked account still binds with connection_id', async () => {
    const { result } = renderHook(() => useOAuthConnect())
    m.listSelectable.mockResolvedValue([TEAM_REPO])

    await act(async () => {
      await result.current.start('p1', 'github', {
        displayName: 'GitHub',
        selection: SELECTION,
        linkedConnection: { id: 'c1', login: 'maya-k' }
      })
    })

    expect(m.createSource).toHaveBeenCalledWith('p1', {
      type: 'github',
      name: 'GitHub',
      connection_id: 'c1'
    })
    expect(m.createSource.mock.calls[0][1]).not.toHaveProperty('installation')
  })

  it('without a teamRepo or account, sign-in still runs', async () => {
    m.startOAuth.mockResolvedValue({ authorize_url: 'https://x', state: 'st' } as never)
    m.exchangeOAuth.mockResolvedValue({ source: { id: 's1' } } as never)
    m.listSelectable.mockResolvedValue([TEAM_REPO])
    const { result } = renderHook(() => useOAuthConnect())

    await act(async () => {
      await result.current.start('p1', 'github', { displayName: 'GitHub', selection: SELECTION })
    })

    expect(m.startOAuth).toHaveBeenCalled()
    expect(awaitOAuth).toHaveBeenCalled()
    expect(m.createSource).not.toHaveBeenCalled()
  })
})
