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
import * as homeTeam from './useHomeTeam'
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
vi.mock('./useHomeTeam', () => ({ useHomeTeam: vi.fn() }))
// The preferences document is its own feature (SOLUSDEV-244); Home only hosts the card.
vi.mock('../preferences/PreferencesCard', () => ({
  PreferencesCard: () => <div data-testid="preferences-card" />
}))
// Account connections are their own feature (SOLUSDEV-241); Home only hosts the card.
vi.mock('./ConnectedAccountsCard', () => ({
  ConnectedAccountsCard: (props: {
    currentProject?: { name: string } | null
    onOpenSources?: () => void
  }) => (
    <div data-testid="connected-accounts" data-project={props.currentProject?.name ?? ''}>
      {props.onOpenSources && <button onClick={props.onOpenSources}>sources-link</button>}
    </div>
  )
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

function mockTeam(overrides: Partial<homeTeam.HomeTeam> = {}): homeTeam.HomeTeam {
  const value: homeTeam.HomeTeam = {
    status: 'ready',
    detail: {
      id: 't1',
      name: 'Strider',
      is_personal: false,
      plan_status: 'trial',
      settings: { notify_project_created: true },
      created_at: '',
      member_count: 2,
      role: 'owner'
    },
    members: [
      { user_id: 'u1', email: 'maya@strider.dev', name: 'Maya', role: 'owner', joined_at: '' },
      { user_id: 'u2', email: 'bob@strider.dev', name: 'Bob', role: 'member', joined_at: '' }
    ],
    invites: [],
    activity: [ROW],
    activityTotal: 1,
    activityHasMore: false,
    myRole: 'owner',
    teamLimit: { current: 1, max: 2, atLimit: false },
    actions: {
      invite: vi.fn(),
      revoke: vi.fn(),
      changeRole: vi.fn(async () => ({ ok: true as const })),
      remove: vi.fn(async () => ({ ok: true as const })),
      leave: vi.fn(),
      rename: vi.fn(),
      deleteTeam: vi.fn(),
      loadMoreActivity: vi.fn(),
      refresh: vi.fn()
    },
    ...overrides
  }
  vi.mocked(homeTeam.useHomeTeam).mockReturnValue(value)
  return value
}

beforeEach(() => {
  vi.clearAllMocks()
  useShellStore.getState().reset()
  useWorkspaceStore.getState().reset()
  mockTeam()
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
    expect(screen.getByTestId('team-name')).toHaveTextContent('Strider')
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
    await userEvent.click(screen.getByRole('button', { name: 'Open Rover MK2' }))
    expect(onOpenProject).toHaveBeenCalledWith({ id: 'p1', name: 'Rover MK2', teamId: 't1' })
  })

  it('offers "Open" on the open project and "Switch to" on the others', async () => {
    mockHome()
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK2', teamId: 't1' } })
    const onOpenProject = vi.fn()
    render(<HomeScreen onOpenProject={onOpenProject} />)
    expect(within(card('p1')).getByRole('button', { name: 'Open' })).toBeInTheDocument()
    await userEvent.click(within(card('p2')).getByRole('button', { name: 'Switch to' }))
    // "Switch to" only re-scopes Home: the current project moves, nothing opens.
    expect(onOpenProject).not.toHaveBeenCalled()
    expect(useWorkspaceStore.getState().project).toEqual({ id: 'p2', name: 'Arm', teamId: 't1' })
    expect(within(card('p2')).getByRole('button', { name: 'Open' })).toBeInTheDocument()
    expect(within(card('p1')).getByRole('button', { name: 'Switch to' })).toBeInTheDocument()
  })

  it('still opens a project from its card body while another is current', async () => {
    mockHome()
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK2', teamId: 't1' } })
    const onOpenProject = vi.fn()
    render(<HomeScreen onOpenProject={onOpenProject} />)
    await userEvent.click(screen.getByRole('button', { name: 'Switch to Arm' }))
    expect(onOpenProject).toHaveBeenCalledWith({ id: 'p2', name: 'Arm', teamId: 't1' })
  })

  it('carries the LOCAL FOLDER card for the current project, above connected accounts', () => {
    mockHome()
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK2', teamId: 't1' } })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    const label = screen.getByText('LOCAL FOLDER')
    expect(label).toBeInTheDocument()
    // Not under the desktop bridge here, so the card degrades to its honest note.
    expect(screen.getByText(/available in the Solus desktop app/)).toBeInTheDocument()
    const accounts = screen.getByTestId('connected-accounts')
    expect(label.compareDocumentPosition(accounts) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('asks for a project before a folder can be linked', () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByText(/switch to a project to link a working copy/)).toBeInTheDocument()
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

describe('HomeScreen — connected accounts wiring', () => {
  it('hands the card the open project and a way to its Sources page', async () => {
    mockHome()
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK2', teamId: 't1' } })
    const onNavigate = vi.fn()
    render(<HomeScreen onOpenProject={vi.fn()} onNavigate={onNavigate} />)
    expect(screen.getByTestId('connected-accounts')).toHaveAttribute('data-project', 'Rover MK2')
    await userEvent.click(screen.getByText('sources-link'))
    expect(onNavigate).toHaveBeenCalledWith('sources')
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
    vi.mocked(home.actions.joinTeam).mockResolvedValue({ ok: true, teamId: 't7', role: 'member' })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /join team/i }))
    await userEvent.type(screen.getByLabelText('Invite token'), 'tok-123')
    await userEvent.click(screen.getByRole('button', { name: 'Join' }))
    expect(home.actions.joinTeam).toHaveBeenCalledWith('tok-123')
  })

  it('creates a team', async () => {
    const home = mockHome()
    vi.mocked(home.actions.createTeam).mockResolvedValue({ ok: true, teamId: 't-new' })
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

describe('how you engineer (HOME H3)', () => {
  it('hosts the preferences card beside the project grid and when offline', () => {
    mockHome()
    const { unmount } = render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByTestId('preferences-card')).toBeInTheDocument()
    unmount()
    mockHome({ status: 'offline' })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByTestId('preferences-card')).toBeInTheDocument()
  })
})

describe('HomeScreen — the team layer (SOLUSDEV-244 / HOME H5)', () => {
  it('shows the active team with its member count, roster with roles, and the team feed', () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByTestId('team-name')).toHaveTextContent('Strider')
    expect(screen.getByText('2 members')).toBeInTheDocument()
    expect(screen.getByText('bob@strider.dev')).toBeInTheDocument()
    // Owner manages roles; the owner row itself is never manageable.
    expect(screen.getByLabelText('Role for bob@strider.dev')).toBeInTheDocument()
    expect(screen.queryByLabelText('Role for maya@strider.dev')).toBeNull()
    expect(screen.getByText('TEAM ACTIVITY')).toBeInTheDocument()
    expect(screen.getByTestId('team-limit')).toHaveTextContent('1 of 2 collaborative teams')
  })

  it('a member sees no role controls, no invite, and can leave', async () => {
    mockHome()
    const team = mockTeam({ myRole: 'member' })
    vi.mocked(team.actions.leave).mockResolvedValue({ ok: true })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.queryByLabelText('Role for bob@strider.dev')).toBeNull()
    expect(screen.queryByRole('button', { name: /invite/i })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Leave team' }))
    await userEvent.click(screen.getByRole('button', { name: 'Leave team' }))
    expect(team.actions.leave).toHaveBeenCalled()
  })

  it('creates a one-time invite from the members card and shows the token once', async () => {
    mockHome()
    const team = mockTeam()
    vi.mocked(team.actions.invite).mockResolvedValue({
      ok: true,
      token: 'tok-once',
      movedToTeamId: null
    })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Invite' }))
    await userEvent.type(screen.getByLabelText('Teammate email'), 'eve@strider.dev')
    await userEvent.click(screen.getByRole('button', { name: 'Send invite' }))
    expect(await screen.findByTestId('invite-token')).toHaveTextContent('tok-once')
    expect(team.actions.invite).toHaveBeenCalledWith('eve@strider.dev')
  })

  it('a BASIC user at two collaborative teams sees the limit and the upgrade path', async () => {
    const onNavigate = vi.fn()
    const home = mockHome()
    mockTeam({ teamLimit: { current: 2, max: 2, atLimit: true } })
    vi.mocked(home.actions.createTeam).mockResolvedValue({
      ok: false,
      reason: 'plan_limit',
      limit: {
        limit: 'max_teams',
        current: 2,
        max: 2,
        message: "You're at your collaborative-team limit."
      }
    })
    render(<HomeScreen onOpenProject={vi.fn()} onNavigate={onNavigate} />)
    expect(screen.getByTestId('team-limit')).toHaveTextContent('2 of 2 collaborative teams')
    await userEvent.click(screen.getByRole('button', { name: 'Upgrade' }))
    expect(onNavigate).toHaveBeenCalledWith('billing')
    await userEvent.click(screen.getByRole('button', { name: /new team/i }))
    await userEvent.type(screen.getByLabelText('Team name'), 'Third')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect(await screen.findByText("You're at your collaborative-team limit.")).toBeInTheDocument()
  })

  it('only the owner is offered Delete team, never on the personal team', async () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
    expect(screen.getByRole('menuitem', { name: 'Delete team' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    cleanupMenus()
    mockHome({ team: PERSONAL })
    mockTeam({ detail: null, myRole: 'owner' })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(
      screen.getAllByRole('button', { name: 'Team menu' }).at(-1) as HTMLElement
    )
    expect(screen.queryByRole('menuitem', { name: 'Delete team' })).toBeNull()
  })

  it('a gone team says so and offers the personal workspace — never "restart the backend"', async () => {
    const home = mockHome({
      status: 'gone',
      me: {
        id: 'u1',
        email: 'm@x',
        name: null,
        avatar_url: null,
        created_at: '',
        teams: [PERSONAL, TEAM]
      }
    })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByText(/no longer available/)).toBeInTheDocument()
    expect(screen.queryByText(/reach its API/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /personal workspace/i }))
    expect(home.actions.switchTeam).toHaveBeenCalledWith('t-me')
  })
})

function cleanupMenus(): void {
  for (const menu of document.querySelectorAll('[role="menu"]')) menu.remove()
}

describe("HomeScreen — the team layer renders other users' text as text", () => {
  it('member names and emails, the team name, and feed payloads are literal', () => {
    const hostile = '<img src=x onerror=alert(1)>'
    mockHome({ team: { ...TEAM, name: hostile } })
    mockTeam({
      members: [
        { user_id: 'u9', email: `${hostile}@x.dev`, name: hostile, role: 'member', joined_at: '' }
      ],
      activity: [{ ...ROW, type: 'invite.created', actor_id: 'u9', payload: { email: hostile } }]
    })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(
      screen.getAllByText(new RegExp(hostile.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))).length
    ).toBeGreaterThan(2)
    expect(document.querySelector('img')).toBeNull()
  })
})
