// Home screen: greeting, projects across teams, recent activity, create flows,
// and the honest offline sign-in state (SOLUSDEV-152 removed the demo project
// card). The data hooks are mocked to drive each state.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HomeScreen } from './HomeScreen'
import * as homeData from './useHomeData'
import * as meHook from './useMe'
import { useShellStore } from './shellStore'

vi.mock('./useHomeData', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./useHomeData')>()
  return { ...actual, useHomeData: vi.fn() }
})
vi.mock('./useMe', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./useMe')>()
  return { ...actual, useMe: vi.fn() }
})

const READY_ME = { status: 'ready' as const, me: null, name: 'Maya', email: 'maya@example.dev' }

const PROJECT = {
  id: 'p1',
  team_id: 't1',
  name: 'Rover MK2',
  description: 'six-wheel rover',
  archived_at: null,
  created_at: '',
  updated_at: ''
}

function homeActions(): homeData.HomeActions {
  return {
    createProject: vi.fn(),
    createTeam: vi.fn(),
    joinTeam: vi.fn(),
    renameProject: vi.fn(),
    archiveProject: vi.fn(),
    unarchiveProject: vi.fn(),
    deleteProject: vi.fn(),
    refresh: vi.fn()
  }
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
    activityTotal: 1,
    actions: homeActions(),
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

  it('shows an honest sign-in state when not linked — never a demo project', () => {
    mockHome({ status: 'offline', groups: [], activity: [] })
    vi.mocked(meHook.useMe).mockReturnValue({ ...READY_ME, status: 'offline' })
    const { container } = render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByText(/Sign in to Solus to see your teams, projects/)).toBeInTheDocument()
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/strider/i)
    expect(text).not.toMatch(/Six-wheel autonomous rover/)
    expect(text).not.toMatch(/YOUR PROJECT/)
  })

  it('renders a spinner while loading', () => {
    mockHome({ status: 'loading', groups: [], activity: [] })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.queryByText('Strider')).not.toBeInTheDocument()
  })

  it('joins a team by pasting an invite token', async () => {
    const home = mockHome()
    vi.mocked(home.actions.joinTeam).mockResolvedValue({ team_id: 't9', role: 'member' })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByText('Join team'))
    await userEvent.type(screen.getByLabelText('Invite token'), 'tok_abc')
    await userEvent.click(screen.getByRole('button', { name: 'Join' }))
    expect(vi.mocked(home.actions.joinTeam)).toHaveBeenCalledWith('tok_abc')
  })

  it('shows an error when the invite token is rejected', async () => {
    const home = mockHome()
    vi.mocked(home.actions.joinTeam).mockResolvedValue(null)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByText('Join team'))
    await userEvent.type(screen.getByLabelText('Invite token'), 'bad')
    await userEvent.click(screen.getByRole('button', { name: 'Join' }))
    expect(await screen.findByText(/couldn.t join/i)).toBeInTheDocument()
  })

  it('renames a project through the row menu', async () => {
    const home = mockHome()
    vi.mocked(home.actions.renameProject).mockResolvedValue(true)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Project actions for Rover MK2' }))
    await userEvent.click(screen.getByText('Rename'))
    const input = screen.getByLabelText('Project name')
    await userEvent.clear(input)
    await userEvent.type(input, 'Rover MK3')
    await userEvent.click(screen.getByText('Save'))
    expect(vi.mocked(home.actions.renameProject)).toHaveBeenCalledWith('p1', 'Rover MK3')
  })

  it('archives a project through the row menu', async () => {
    const home = mockHome()
    vi.mocked(home.actions.archiveProject).mockResolvedValue(true)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Project actions for Rover MK2' }))
    await userEvent.click(screen.getByText('Archive'))
    expect(vi.mocked(home.actions.archiveProject)).toHaveBeenCalledWith('p1')
  })

  it('deletes a project only after confirming', async () => {
    const home = mockHome()
    vi.mocked(home.actions.deleteProject).mockResolvedValue(true)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Project actions for Rover MK2' }))
    await userEvent.click(screen.getByText('Delete'))
    expect(vi.mocked(home.actions.deleteProject)).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Delete project' }))
    expect(vi.mocked(home.actions.deleteProject)).toHaveBeenCalledWith('p1')
  })

  it('keeps the rename dialog open and shows an error when rename fails', async () => {
    const home = mockHome()
    vi.mocked(home.actions.renameProject).mockResolvedValue(false)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Project actions for Rover MK2' }))
    await userEvent.click(screen.getByText('Rename'))
    await userEvent.click(screen.getByText('Save'))
    expect(await screen.findByText(/couldn.t rename/i)).toBeInTheDocument()
    // Dialog stays open so the user can retry.
    expect(screen.getByLabelText('Project name')).toBeInTheDocument()
  })

  it('keeps the delete dialog open and shows an error when delete fails', async () => {
    const home = mockHome()
    vi.mocked(home.actions.deleteProject).mockResolvedValue(false)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Project actions for Rover MK2' }))
    await userEvent.click(screen.getByText('Delete'))
    await userEvent.click(screen.getByRole('button', { name: 'Delete project' }))
    expect(await screen.findByText(/couldn.t delete/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete project' })).toBeInTheDocument()
  })

  it('shows a toast when archiving fails', async () => {
    useShellStore.getState().reset()
    const home = mockHome()
    vi.mocked(home.actions.archiveProject).mockResolvedValue(false)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Project actions for Rover MK2' }))
    await userEvent.click(screen.getByText('Archive'))
    await vi.waitFor(() => expect(useShellStore.getState().toast).not.toBeNull())
    expect(useShellStore.getState().toast?.kind).toBe('warn')
  })

  it('lists archived projects with an unarchive action', async () => {
    const home = mockHome({
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
          projects: [{ ...PROJECT, id: 'p2', name: 'Old Rig', archived_at: '2026-01-01T00:00:00Z' }]
        }
      ]
    })
    vi.mocked(home.actions.unarchiveProject).mockResolvedValue(true)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByText('Old Rig')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Unarchive Old Rig' }))
    expect(vi.mocked(home.actions.unarchiveProject)).toHaveBeenCalledWith('p2')
  })

  it('shows no view-all affordance when the feed fits the panel', () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.queryByText(/View all activity/)).not.toBeInTheDocument()
  })

  it('truncates recent activity to six rows and opens the all-activity dialog', async () => {
    const eight = Array.from({ length: 8 }, (_, i) => ({
      id: `a${i + 1}`,
      type: 'project.created',
      domain: null,
      actor_id: 'u1',
      project_id: 'p1',
      payload: { name: 'Rover MK2' },
      created_at: `2026-07-06T00:00:${String(59 - i).padStart(2, '0')}Z`
    }))
    mockHome({ activity: eight, activityTotal: 20 })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getAllByText(/created the project/)).toHaveLength(6)
    await userEvent.click(screen.getByRole('button', { name: /View all activity \(20\)/ }))
    const dialog = screen.getByRole('dialog', { name: 'All activity' })
    expect(within(dialog).getAllByText(/created the project/)).toHaveLength(8)
    // The merged cross-team feed has no cursor to follow — no Load more here.
    expect(within(dialog).queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })

  it('hides management actions for viewers', () => {
    mockHome({
      groups: [
        {
          team: {
            team_id: 't1',
            name: 'Strider',
            role: 'viewer',
            is_personal: false,
            plan_status: 'trial',
            trial_ends_at: ''
          },
          projects: [PROJECT]
        }
      ]
    })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(
      screen.queryByRole('button', { name: 'Project actions for Rover MK2' })
    ).not.toBeInTheDocument()
  })
})
