import { describe, it, expect, vi, beforeEach } from 'vitest'
import { deriveProjectName, provisionWorkspace, ensureWorkspace } from './provisioning'
import * as resources from '../../lib/api/resources'
import { ApiError } from '../../lib/api/envelope.types'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    getMe: vi.fn(),
    getProject: vi.fn(),
    createProject: vi.fn(),
    updateSolMode: vi.fn()
  }
})

const mockedGetMe = vi.mocked(resources.getMe)
const mockedGetProject = vi.mocked(resources.getProject)
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
  return {
    id: 'p1',
    team_id: 't1',
    name,
    description: null,
    archived_at: null,
    created_at: '',
    updated_at: ''
  }
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
    mockedGetProject.mockResolvedValue({ id: 'p1', name: 'Strider' } as never)

    const result = await ensureWorkspace({
      description: 'whatever',
      solMode: 'Guide',
      existing: { teamId: 't1', project: { id: 'p1', name: 'Strider' } }
    })
    expect(result).toEqual({ linked: true, teamId: 't1', project: { id: 'p1', name: 'Strider' } })
    expect(mockedGetMe).not.toHaveBeenCalled()
    expect(mockedCreateProject).not.toHaveBeenCalled()
  })

  // A persisted project id outlives the row it names: a teammate deletes the
  // project, the user leaves the team, the database is restored. Reusing it
  // blindly leaves every project-scoped screen 404ing with no way back.
  it('discards a persisted project the server no longer has, and creates a fresh one', async () => {
    mockedGetProject.mockRejectedValue(new ApiError(404, 'not_found', 'Project not found'))
    mockedGetMe.mockResolvedValue(personalUser('a@b.dev'))
    mockedCreateProject.mockResolvedValue(createdProject('Strider'))
    mockedUpdateSolMode.mockResolvedValue({})

    const result = await ensureWorkspace({
      description: 'Strider',
      solMode: 'Guide',
      existing: { teamId: 't1', project: { id: 'dead', name: 'Gone' } }
    })

    expect(mockedCreateProject).toHaveBeenCalled()
    expect(result.linked).toBe(true)
    expect(result.project?.id).not.toBe('dead')
  })

  // The other half: "could not reach the server" must never be read as "your
  // project is gone", or a blip silently discards a good workspace.
  it.each([
    ['401', new ApiError(401, 'unauthorized', 'nope')],
    ['500', new ApiError(500, 'server_error', 'boom')],
    ['network failure', new Error('Failed to fetch')]
  ])('keeps the persisted project when validation fails with %s', async (_label, error) => {
    mockedGetProject.mockRejectedValue(error)

    const result = await ensureWorkspace({
      description: 'whatever',
      solMode: 'Guide',
      existing: { teamId: 't1', project: { id: 'p1', name: 'Strider' } }
    })

    expect(result).toEqual({ linked: true, teamId: 't1', project: { id: 'p1', name: 'Strider' } })
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
