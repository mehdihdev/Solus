import { describe, it, expect, vi, beforeEach } from 'vitest'
import { deriveProjectName, provisionWorkspace, ensureWorkspace } from './provisioning'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    getMe: vi.fn(),
    createProject: vi.fn(),
    updateSolMode: vi.fn()
  }
})

const mockedGetMe = vi.mocked(resources.getMe)
const mockedCreateProject = vi.mocked(resources.createProject)
const mockedUpdateSolMode = vi.mocked(resources.updateSolMode)

describe('deriveProjectName', () => {
  it('uses the first sentence of the description', () => {
    expect(deriveProjectName('A 12-DOF quadruped. STM32 firmware')).toBe('A 12-DOF quadruped')
  })

  it('falls back to a default when empty', () => {
    expect(deriveProjectName('   ')).toBe('My first robot')
  })

  it('truncates very long names', () => {
    const name = deriveProjectName('x'.repeat(200))
    expect(name.length).toBeLessThanOrEqual(81)
    expect(name.endsWith('…')).toBe(true)
  })
})

type MeResponse = Awaited<ReturnType<typeof resources.getMe>>
type CreatedProject = Awaited<ReturnType<typeof resources.createProject>>

/** A user whose only team is their personal one — the common provisioning fixture. */
function personalUser(email: string): MeResponse {
  return {
    id: 'u1',
    email,
    name: null,
    avatar_url: null,
    created_at: '',
    teams: [
      {
        team_id: 't1',
        name: 'Personal',
        role: 'owner',
        is_personal: true,
        plan_status: 'trial',
        trial_ends_at: ''
      }
    ]
  }
}

function createdProject(name: string): CreatedProject {
  return { id: 'p1', team_id: 't1', name, description: null, created_at: '', updated_at: '' }
}

describe('provisionWorkspace', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('creates a project under the personal team and reports linked', async () => {
    mockedGetMe.mockResolvedValue(personalUser('maya@strider.dev'))
    mockedCreateProject.mockResolvedValue(createdProject('Strider'))
    mockedUpdateSolMode.mockResolvedValue({})

    const result = await provisionWorkspace({ description: 'Strider quadruped', solMode: 'Expert' })

    expect(result.linked).toBe(true)
    expect(result.teamId).toBe('t1')
    expect(result.project).toEqual({ id: 'p1', name: 'Strider' })
    expect(mockedCreateProject).toHaveBeenCalledWith('t1', {
      name: 'Strider quadruped',
      description: 'Strider quadruped'
    })
    expect(mockedUpdateSolMode).toHaveBeenCalledWith('Expert')
  })

  it('degrades to unlinked when the API is unreachable (never throws)', async () => {
    mockedGetMe.mockRejectedValue(new Error('Failed to fetch'))
    const result = await provisionWorkspace({ description: 'anything', solMode: 'Guide' })
    expect(result.linked).toBe(false)
    expect(result.error).toContain('Failed to fetch')
  })

  it('still links even if persisting SOL mode fails', async () => {
    mockedGetMe.mockResolvedValue(personalUser('a@b.dev'))
    mockedCreateProject.mockResolvedValue(createdProject('X'))
    mockedUpdateSolMode.mockRejectedValue(new Error('settings 500'))

    const result = await provisionWorkspace({ description: 'X', solMode: 'Guide' })
    expect(result.linked).toBe(true)
  })
})

describe('ensureWorkspace', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('reuses an existing project without creating a second one', async () => {
    const result = await ensureWorkspace({
      description: 'whatever',
      solMode: 'Guide',
      existing: { teamId: 't1', project: { id: 'p1', name: 'Strider' } }
    })
    expect(result).toEqual({ linked: true, teamId: 't1', project: { id: 'p1', name: 'Strider' } })
    expect(mockedGetMe).not.toHaveBeenCalled()
    expect(mockedCreateProject).not.toHaveBeenCalled()
  })

  it('creates the project when none exists yet', async () => {
    mockedGetMe.mockResolvedValue(personalUser('a@b.dev'))
    mockedCreateProject.mockResolvedValue(createdProject('Strider'))
    mockedUpdateSolMode.mockResolvedValue({})

    const result = await ensureWorkspace({ description: 'Strider', solMode: 'Guide' })
    expect(result.linked).toBe(true)
    expect(result.project).toEqual({ id: 'p1', name: 'Strider' })
    expect(mockedCreateProject).toHaveBeenCalledTimes(1)
  })

  it('degrades to unlinked when the API is unreachable and no project exists', async () => {
    mockedGetMe.mockRejectedValue(new Error('Failed to fetch'))
    const result = await ensureWorkspace({ description: 'x', solMode: 'Guide' })
    expect(result.linked).toBe(false)
  })
})
