// Home screen: greeting, projects across teams, recent activity, create flows,
// and the offline demo fallback. The data hooks are mocked to drive each state.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HomeScreen } from './HomeScreen'
import * as homeData from './useHomeData'
import * as meHook from './useMe'
import { FALLBACK_PROJECT_NAME } from './workspaceData.constants'

vi.mock('./useHomeData', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./useHomeData')>()
  return { ...actual, useHomeData: vi.fn() }
})
vi.mock('./useMe', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./useMe')>()
  return { ...actual, useMe: vi.fn() }
})

const READY_ME = { status: 'ready' as const, me: null, name: 'Maya', email: 'maya@strider.dev' }

const PROJECT = {
  id: 'p1',
  team_id: 't1',
  name: 'Rover MK2',
  description: 'six-wheel rover',
  created_at: '',
  updated_at: ''
}

function mockHome(overrides: Partial<homeData.HomeData> = {}): homeData.HomeData {
  const value: homeData.HomeData = {
    status: 'ready',
    me: null,
    groups: [
      {
        team: {
          team_id: 't1',
          name: 'Strider',
          role: 'owner',
          is_personal: false,
          plan_status: 'trial',
          trial_ends_at: ''
        },
        projects: [PROJECT]
      }
    ],
    activity: [
      {
        id: 'a1',
        type: 'project.created',
        domain: null,
        actor_id: 'u1',
        project_id: 'p1',
        payload: { name: 'Rover MK2' },
        created_at: '2026-07-06T00:00:00Z'
      }
    ],
    actions: { createProject: vi.fn(), createTeam: vi.fn(), refresh: vi.fn() },
    ...overrides
  }
  vi.mocked(homeData.useHomeData).mockReturnValue(value)
  return value
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(meHook.useMe).mockReturnValue(READY_ME)
})

describe('HomeScreen', () => {
  it('greets the user and lists projects grouped by team', () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByText('Welcome back, Maya')).toBeInTheDocument()
    expect(screen.getByText('Strider')).toBeInTheDocument()
    expect(screen.getByText('Rover MK2')).toBeInTheDocument()
    expect(screen.getByText(/created the project/)).toBeInTheDocument()
  })

  it('opens a project when its row is clicked', async () => {
    mockHome()
    const onOpenProject = vi.fn()
    render(<HomeScreen onOpenProject={onOpenProject} />)
    await userEvent.click(screen.getByText('Rover MK2'))
    expect(onOpenProject).toHaveBeenCalledWith({ id: 'p1', name: 'Rover MK2' })
  })

  it('creates a project through the new-project modal', async () => {
    const home = mockHome()
    vi.mocked(home.actions.createProject).mockResolvedValue(PROJECT)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByText('New project'))
    await userEvent.type(screen.getByLabelText('Project name'), 'Rover MK2')
    await userEvent.click(screen.getByText('Create'))
    expect(vi.mocked(home.actions.createProject)).toHaveBeenCalledWith('t1', 'Rover MK2')
  })

  it('shows the offline demo project when not linked', () => {
    mockHome({ status: 'offline', groups: [], activity: [] })
    vi.mocked(meHook.useMe).mockReturnValue({ ...READY_ME, status: 'offline' })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByText(FALLBACK_PROJECT_NAME)).toBeInTheDocument()
  })

  it('renders a spinner while loading', () => {
    mockHome({ status: 'loading', groups: [], activity: [] })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.queryByText('Strider')).not.toBeInTheDocument()
  })
})
