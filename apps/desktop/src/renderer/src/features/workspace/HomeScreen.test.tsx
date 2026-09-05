// Home (SOLUSDEV-242 / HOME H1): the active team's project grid — create,
// open, switch, archive, per-project activity — the team selector, the
// account-level actions, and the honest offline state. The data hooks are
// mocked to drive each state.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HomeScreen } from './HomeScreen'
import * as homeData from './useHomeData'
import * as meHook from './useMe'
import * as projectActivity from './useProjectActivity'
import { useShellStore } from './shellStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { ActivityApi, Project, TeamSummary } from '../../lib/api/resources'

vi.mock('./useHomeData', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./useHomeData')>()
  return { ...actual, useHomeData: vi.fn() }
})
vi.mock('./useMe', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./useMe')>()
  return { ...actual, useMe: vi.fn() }
})
vi.mock('./useProjectActivity', () => ({ useProjectActivity: vi.fn() }))
// Account connections are their own feature (SOLUSDEV-241); Home only hosts the card.
vi.mock('./ConnectedAccountsCard', () => ({
  ConnectedAccountsCard: () => <div data-testid="connected-accounts" />
}))

const READY_ME = { status: 'ready' as const, me: null, name: 'Maya', email: 'maya@example.dev' }

const TEAM: TeamSummary = {
  team_id: 't1',
  name: 'Strider',
  role: 'owner',
  is_personal: false,
  plan_status: 'trial',
  trial_ends_at: ''
}
const PERSONAL: TeamSummary = { ...TEAM, team_id: 't-me', name: 'Maya', is_personal: true }
const PROJECT: Project = {
  id: 'p1',
  team_id: 't1',
  name: 'Rover MK2',
  description: 'six-wheel rover',
  archived_at: null,
  created_at: '',
  updated_at: ''
}
const ARM: Project = { ...PROJECT, id: 'p2', name: 'Arm', description: null }
const ROW: ActivityApi = {
  id: 'a1',
  type: 'project.created',
  domain: null,
  actor_id: 'u1',
  project_id: 'p1',
  payload: { name: 'Rover MK2' },
  created_at: '2026-07-06T00:00:00Z'
}

function homeActions(): homeData.HomeActions {
  return {
    switchTeam: vi.fn(),
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
    teams: [PERSONAL, TEAM],
    team: TEAM,
    projects: [PROJECT, ARM],
    activityByProject: { p1: [ROW] },
    actions: homeActions(),
    ...overrides
  }
  vi.mocked(homeData.useHomeData).mockReturnValue(value)
  return value
}

const card = (id: string): HTMLElement => screen.getByTestId(`project-card-${id}`)

beforeEach(() => {
  vi.clearAllMocks()
  useShellStore.getState().reset()
  useWorkspaceStore.getState().reset()
  vi.mocked(meHook.useMe).mockReturnValue(READY_ME)
  vi.mocked(projectActivity.useProjectActivity).mockReturnValue({
    status: 'ready',
    activity: [ROW],
    total: 1,
    hasMore: false,
    loadMore: vi.fn()
  })
})

describe('HomeScreen — the active team’s project grid', () => {
  it('greets the user and lists the active team’s projects as cards', () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByText('Welcome back, Maya')).toBeInTheDocument()
    expect(screen.getByText('Projects in Strider')).toBeInTheDocument()
    const grid = screen.getByTestId('project-grid')
    expect(within(grid).getByText('Rover MK2')).toBeInTheDocument()
    expect(within(grid).getByText('Arm')).toBeInTheDocument()
    expect(within(grid).getByText('six-wheel rover')).toBeInTheDocument()
    expect(screen.getByTestId('connected-accounts')).toBeInTheDocument()
  })

  it('shows each project its OWN recent activity, and honest emptiness for the rest', () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(within(card('p1')).getByText(/created the project/)).toBeInTheDocument()
    expect(within(card('p2')).queryByText(/created the project/)).toBeNull()
    expect(within(card('p2')).getByText('No recent activity.')).toBeInTheDocument()
  })

  it('opens a project (with its team) from its card', async () => {
    mockHome()
    const onOpenProject = vi.fn()
    render(<HomeScreen onOpenProject={onOpenProject} />)
    await userEvent.click(within(card('p1')).getByRole('button', { name: 'Open Rover MK2' }))
    expect(onOpenProject).toHaveBeenCalledWith({ id: 'p1', name: 'Rover MK2', teamId: 't1' })
  })

  it('marks the open project CURRENT and offers "Switch to" on the others', async () => {
    mockHome()
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK2', teamId: 't1' } })
    const onOpenProject = vi.fn()
    render(<HomeScreen onOpenProject={onOpenProject} />)
    expect(within(card('p1')).getByText('CURRENT')).toBeInTheDocument()
    expect(within(card('p2')).queryByText('CURRENT')).toBeNull()
    expect(within(card('p1')).getByRole('button', { name: 'Open' })).toBeInTheDocument()
    await userEvent.click(within(card('p2')).getByRole('button', { name: 'Switch to' }))
    expect(onOpenProject).toHaveBeenCalledWith({ id: 'p2', name: 'Arm', teamId: 't1' })
  })

  it('switches the active team from the selector', async () => {
    const home = mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.selectOptions(screen.getByLabelText('Switch team'), 't-me')
    expect(home.actions.switchTeam).toHaveBeenCalledWith('t-me')
  })

  it('hides the team selector with a single team', () => {
    mockHome({ teams: [TEAM] })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.queryByLabelText('Switch team')).toBeNull()
  })

  it('creates a project in the active team and opens it', async () => {
    const home = mockHome()
    vi.mocked(home.actions.createProject).mockResolvedValue(ARM)
    const onOpenProject = vi.fn()
    render(<HomeScreen onOpenProject={onOpenProject} />)
    await userEvent.click(screen.getByRole('button', { name: /new project/i }))
    await userEvent.type(screen.getByLabelText('Project name'), 'Arm')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect(home.actions.createProject).toHaveBeenCalledWith('Arm')
    expect(onOpenProject).toHaveBeenCalledWith({ id: 'p2', name: 'Arm', teamId: 't1' })
  })

  it('opens the project’s full activity dialog from its card', async () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(within(card('p2')).getByRole('button', { name: /all activity/i }))
    expect(vi.mocked(projectActivity.useProjectActivity)).toHaveBeenCalledWith('t1', 'p2')
    const dialog = screen.getByRole('dialog', { name: 'Arm — activity' })
    expect(within(dialog).getByText(/created the project/)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('HomeScreen — manage', () => {
  it('renames a project through the card menu', async () => {
    const home = mockHome()
    vi.mocked(home.actions.renameProject).mockResolvedValue(true)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Project actions for Rover MK2' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Rename' }))
    const input = screen.getByLabelText('Project name')
    await userEvent.clear(input)
    await userEvent.type(input, 'Rover MK3')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(home.actions.renameProject).toHaveBeenCalledWith('p1', 'Rover MK3')
  })

  it('archives a project through the card menu — the menu never opens the project', async () => {
    const home = mockHome()
    vi.mocked(home.actions.archiveProject).mockResolvedValue(true)
    const onOpenProject = vi.fn()
    render(<HomeScreen onOpenProject={onOpenProject} />)
    await userEvent.click(screen.getByRole('button', { name: 'Project actions for Rover MK2' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Archive' }))
    expect(home.actions.archiveProject).toHaveBeenCalledWith('p1')
    expect(onOpenProject).not.toHaveBeenCalled()
  })

  it('shows a toast when archiving fails', async () => {
    const home = mockHome()
    vi.mocked(home.actions.archiveProject).mockResolvedValue(false)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Project actions for Rover MK2' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Archive' }))
    await vi.waitFor(() =>
      expect(useShellStore.getState().toast?.body).toBe('Couldn\'t archive "Rover MK2".')
    )
  })

  it('deletes a project only after confirming', async () => {
    const home = mockHome()
    vi.mocked(home.actions.deleteProject).mockResolvedValue(true)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Project actions for Rover MK2' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    expect(home.actions.deleteProject).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /^delete project$/i }))
    expect(home.actions.deleteProject).toHaveBeenCalledWith('p1')
  })

  it('keeps archived projects out of the grid, behind a collapsed count, with unarchive and delete', async () => {
    const home = mockHome({
      projects: [PROJECT, { ...ARM, archived_at: '2026-07-01T00:00:00Z' }]
    })
    vi.mocked(home.actions.unarchiveProject).mockResolvedValue(true)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(within(screen.getByTestId('project-grid')).queryByText('Arm')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Unarchive Arm' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /archived \(1\)/i }))
    expect(screen.getByRole('button', { name: 'Delete Arm' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Unarchive Arm' }))
    expect(home.actions.unarchiveProject).toHaveBeenCalledWith('p2')
  })

  it('hides management actions and the new-project tile for viewers', () => {
    mockHome({ team: { ...TEAM, role: 'viewer' } })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.queryByRole('button', { name: /project actions/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /new project/i })).toBeNull()
  })

  it('hides delete for admins and members — only an owner deletes (ADR-025)', async () => {
    mockHome({ team: { ...TEAM, role: 'admin' } })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Project actions for Rover MK2' }))
    expect(screen.getByRole('menuitem', { name: 'Archive' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Delete' })).toBeNull()
  })
})

describe('HomeScreen — untrusted text is text', () => {
  it('renders project names, descriptions and activity payloads as literal text, never markup', () => {
    const hostile = '<img src=x onerror="alert(1)">'
    mockHome({
      projects: [{ ...PROJECT, name: hostile, description: '<b>bold</b>' }],
      activityByProject: {
        p1: [{ ...ROW, type: 'source.connected', payload: { type: '<script>', name: hostile } }]
      }
    })
    const { container } = render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(container.querySelector('img, script, b')).toBeNull()
    expect(screen.getAllByText(hostile).length).toBeGreaterThan(0)
    expect(screen.getByText('<b>bold</b>')).toBeInTheDocument()
  })
})

describe('HomeScreen — teams and states', () => {
  it('joins a team by pasting an invite token', async () => {
    const home = mockHome()
    vi.mocked(home.actions.joinTeam).mockResolvedValue({ team_id: 't7', role: 'member' })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /join team/i }))
    await userEvent.type(screen.getByLabelText('Invite token'), 'tok-123')
    await userEvent.click(screen.getByRole('button', { name: 'Join' }))
    expect(home.actions.joinTeam).toHaveBeenCalledWith('tok-123')
  })

  it('creates a team', async () => {
    const home = mockHome()
    vi.mocked(home.actions.createTeam).mockResolvedValue(true)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /new team/i }))
    await userEvent.type(screen.getByLabelText('Team name'), 'Rocket Lab')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect(home.actions.createTeam).toHaveBeenCalledWith('Rocket Lab')
  })

  it('explains an empty team and offers the new-project tile', () => {
    mockHome({ projects: [], activityByProject: {} })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByText('Create one to start building the graph.')).toBeInTheDocument()
  })

  it('explains being on no team at all', () => {
    mockHome({ teams: [], team: null, projects: [], activityByProject: {} })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByText(/not on any teams yet/)).toBeInTheDocument()
    expect(screen.queryByTestId('project-grid')).toBeNull()
  })

  it('shows an honest sign-in state when not linked — never a demo project', () => {
    mockHome({ status: 'offline', teams: [], team: null, projects: [], activityByProject: {} })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByText(/sign in to solus/i)).toBeInTheDocument()
    expect(screen.queryByTestId('project-grid')).toBeNull()
  })

  it('renders a spinner while loading', () => {
    mockHome({ status: 'loading', projects: [] })
    const { container } = render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(container.querySelector('[data-spinner]') ?? container.firstChild).toBeTruthy()
    expect(screen.queryByTestId('project-grid')).toBeNull()
  })
})
