// Home (SOLUSDEV-242 / HOME H1; SOLUSDEV-317 layout): the active team's
// project list — create, select, open, archive, per-project activity — the
// one pane beside it (Project / Members / Connected accounts views), the team
// selector, the account-level actions, and the honest offline state. The data
// hooks are mocked to drive each state.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HomeScreen } from './HomeScreen'
import * as homeData from './useHomeData'
import * as meHook from './useMe'
import * as projectActivity from './useProjectActivity'
import * as homeTeam from './useHomeTeam'
import * as projectRepos from './useProjectRepos'
import * as projectSources from '../project/useProjectSources'
import { useShellStore } from './shellStore'
import { useGithubAssignFocusStore } from './githubAssignFocusStore'
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
// Repos per project are read by their own hook (useProjectRepos.test.ts); the
// current project's comes from its live source list.
vi.mock('./useProjectRepos', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./useProjectRepos')>()
  return { ...actual, useProjectRepos: vi.fn(() => ({})) }
})
vi.mock('../project/useProjectSources', () => ({
  useProjectSources: vi.fn(() => ({
    status: 'offline',
    sources: [],
    actions: { refresh: vi.fn(), syncNow: vi.fn(), disconnect: vi.fn() }
  }))
}))
// The project's sources are their own block (ProjectSourcesSummary.test.tsx);
// Home only hosts it and routes its "Add additional sources".
vi.mock('./ProjectSourcesSummary', () => ({
  ProjectSourcesSummary: ({ onAdd }: { onAdd: () => void }) => (
    <button type="button" data-testid="project-sources" onClick={onAdd}>
      Add additional sources
    </button>
  )
}))
// The preferences document is its own feature (SOLUSDEV-244); Home only hosts the card.
vi.mock('./SolusCard', () => ({
  SolusCard: ({ projectId }: { projectId: string | null }) => (
    <div data-testid="solus-card" data-project={projectId ?? ''} />
  )
}))
// Account connections are their own feature (SOLUSDEV-241); Home only hosts the card.
vi.mock('./ConnectedAccountsCard', () => ({
  ConnectedAccountsCard: (props: { currentProject?: { name: string } | null }) => (
    <div data-testid="connected-accounts" data-project={props.currentProject?.name ?? ''} />
  )
}))

// The GitHub card + org members section are their own feature (SOLUSDEV-216 /
// SOLUSDEV-317); Home only hosts them. `orgSection.shown` stands in for "an
// owner/admin with a live Organization link".
const orgSection = vi.hoisted(() => ({ shown: false }))
vi.mock('./TeamGithubPanel', async () => {
  const { useEffect } = await import('react')
  return {
    TeamGithubPanel: (props: {
      teamId: string
      teamName: string
      canManage: boolean
      onSectionChange?: (shown: boolean) => void
    }) => {
      const { onSectionChange } = props
      useEffect(() => onSectionChange?.(orgSection.shown), [onSectionChange])
      return (
        <div
          data-testid="github-org-card"
          data-team={props.teamId}
          data-team-name={props.teamName}
          data-manage={String(props.canManage)}
        />
      )
    }
  }
})

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
    editProject: vi.fn(),
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

const row = (id: string): HTMLElement => screen.getByTestId(`project-row-${id}`)
const pane = (): HTMLElement => screen.getByTestId('home-pane')
const ROVER = { id: 'p1', name: 'Rover MK2', teamId: 't1' }

async function showMembers(): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: /^team & invites/i }))
}

async function teamMenuPick(name: RegExp): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
  await userEvent.click(screen.getByRole('menuitem', { name }))
}

async function showAccounts(): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: /^connected accounts/i }))
}

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

describe('HomeScreen — the active team’s project list', () => {
  homeProjectNavigationTests()
  homeTeamProjectContextTests()
})

describe('HomeScreen — connected accounts view', () => {
  it('is one click away in the pane, handed the current project', async () => {
    mockHome()
    useWorkspaceStore.setState({ project: ROVER })
    render(<HomeScreen onOpenProject={vi.fn()} onNavigate={vi.fn()} />)
    expect(screen.queryByTestId('connected-accounts')).toBeNull()
    await showAccounts()
    expect(within(pane()).getByTestId('connected-accounts')).toHaveAttribute(
      'data-project',
      'Rover MK2'
    )
    expect(screen.getByRole('button', { name: /^connected accounts/i })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
  })

  it("opens from the project's Add additional sources link", async () => {
    mockHome()
    useWorkspaceStore.setState({ project: ROVER })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(within(pane()).getByRole('button', { name: 'Add additional sources' }))
    expect(within(pane()).getByTestId('connected-accounts')).toBeInTheDocument()
  })

  it('offers a way back to the project it was opened from', async () => {
    mockHome()
    useWorkspaceStore.setState({ project: ROVER })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(within(pane()).getByRole('button', { name: 'Add additional sources' }))
    await userEvent.click(within(pane()).getByRole('button', { name: 'Back to Rover MK2' }))
    expect(within(pane()).getByRole('heading', { name: 'Rover MK2' })).toBeInTheDocument()
    expect(within(pane()).queryByTestId('connected-accounts')).toBeNull()
  })

  it('has no back button when opened from the sidebar', async () => {
    mockHome()
    useWorkspaceStore.setState({ project: ROVER })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(within(pane()).getByRole('button', { name: 'Add additional sources' }))
    await showAccounts()
    expect(within(pane()).queryByRole('button', { name: /^back to/i })).toBeNull()
  })
})

describe('HomeScreen — GitHub organization card', () => {
  it('mounts for a collaborative team, scoped to it, with admin gating from the role', async () => {
    mockHome()
    mockTeam({ myRole: 'member' })
    render(<HomeScreen onOpenProject={vi.fn()} onNavigate={vi.fn()} />)
    await showMembers()
    const card = screen.getByTestId('github-org-card')
    expect(card).toHaveAttribute('data-team', 't1')
    expect(card).toHaveAttribute('data-manage', 'false')
  })

  it('lets an owner manage', async () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} onNavigate={vi.fn()} />)
    await showMembers()
    expect(screen.getByTestId('github-org-card')).toHaveAttribute('data-manage', 'true')
  })

  it('is absent on the personal team', async () => {
    mockHome({ team: PERSONAL })
    render(<HomeScreen onOpenProject={vi.fn()} onNavigate={vi.fn()} />)
    await showMembers()
    expect(screen.queryByTestId('github-org-card')).toBeNull()
  })

  it('is absent until the team layer is ready', () => {
    mockHome()
    mockTeam({ status: 'loading' })
    render(<HomeScreen onOpenProject={vi.fn()} onNavigate={vi.fn()} />)
    expect(screen.queryByTestId('github-org-card')).toBeNull()
  })

  it('orders Team & invites: members, GitHub, team activity', async () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} onNavigate={vi.fn()} />)
    await showMembers()
    const text = pane().textContent ?? ''
    const card = screen.getByTestId('github-org-card')
    expect(card).toHaveAttribute('data-team-name', 'Strider')
    expect(text.indexOf('MEMBERS ·')).toBeLessThan(text.indexOf('TEAM ACTIVITY'))
    const position = card.compareDocumentPosition(screen.getByText('TEAM ACTIVITY'))
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('offers "Assign GitHub…" only while the org members section is shown', async () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} onNavigate={vi.fn()} />)
    await showMembers()
    expect(screen.queryByRole('button', { name: /^assign github/i })).toBeNull()
  })

  it('"Assign GitHub…" asks the section to work from that teammate', async () => {
    orgSection.shown = true
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} onNavigate={vi.fn()} />)
    await showMembers()
    const buttons = await screen.findAllByRole('button', { name: /^assign github/i })
    await userEvent.click(buttons[0])
    expect(useGithubAssignFocusStore.getState().request).toMatchObject({ teamId: 't1' })
    orgSection.shown = false
  })
})

describe('HomeScreen — manage', () => {
  homeProjectManagementTests()
  homeProjectManagementPermissionsTests()
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
    await teamMenuPick(/join team/i)
    await userEvent.type(screen.getByLabelText('Invite token'), 'tok-123')
    await userEvent.click(screen.getByRole('button', { name: 'Join' }))
    expect(home.actions.joinTeam).toHaveBeenCalledWith('tok-123')
  })

  it('creates a team', async () => {
    const home = mockHome()
    vi.mocked(home.actions.createTeam).mockResolvedValue({ ok: true, teamId: 't-new' })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await teamMenuPick(/new team/i)
    await userEvent.type(screen.getByLabelText('Team name'), 'Rocket Lab')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect(home.actions.createTeam).toHaveBeenCalledWith('Rocket Lab')
  })

  it('explains an empty team and offers a new project', () => {
    mockHome({ projects: [], activityByProject: {} })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByText('Create one to start building the graph.')).toBeInTheDocument()
  })

  it('explains being on no team at all', () => {
    mockHome({ teams: [], team: null, projects: [], activityByProject: {} })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByText(/not on any teams yet/)).toBeInTheDocument()
    expect(screen.queryByTestId('project-list')).toBeNull()
  })

  it('shows an honest sign-in state when not linked — never a demo project', () => {
    mockHome({ status: 'offline', teams: [], team: null, projects: [], activityByProject: {} })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByText(/sign in to solus/i)).toBeInTheDocument()
    expect(screen.queryByTestId('project-list')).toBeNull()
  })

  it('renders a spinner while loading', () => {
    mockHome({ status: 'loading', projects: [] })
    const { container } = render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(container.querySelector('[data-spinner]') ?? container.firstChild).toBeTruthy()
    expect(screen.queryByTestId('project-list')).toBeNull()
  })
})

describe('the .solus card (SOLUSDEV-253)', () => {
  it("hosts the current project's .solus in its own tab, and nothing offline", async () => {
    mockHome()
    useWorkspaceStore.setState({ project: ROVER })
    const { unmount } = render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(within(pane()).getByRole('tab', { name: '.solus' }))
    expect(screen.getByTestId('solus-card')).toHaveAttribute('data-project', 'p1')
    unmount()
    mockHome({ status: 'offline' })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.queryByTestId('solus-card')).toBeNull()
  })
})

describe('HomeScreen — the team layer (SOLUSDEV-244 / HOME H5)', () => {
  homeTeamMembershipTests()
  homeTeamLimitsAndAvailabilityTests()
})

function cleanupMenus(): void {
  for (const menu of document.querySelectorAll('[role="menu"]')) menu.remove()
}

describe("HomeScreen — the team layer renders other users' text as text", () => {
  it('member names and emails, the team name, and feed payloads are literal', async () => {
    const hostile = '<img src=x onerror=alert(1)>'
    mockHome({ team: { ...TEAM, name: hostile } })
    mockTeam({
      members: [
        { user_id: 'u9', email: `${hostile}@x.dev`, name: hostile, role: 'member', joined_at: '' }
      ],
      activity: [{ ...ROW, type: 'invite.created', actor_id: 'u9', payload: { email: hostile } }]
    })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await showMembers()
    expect(
      screen.getAllByText(new RegExp(hostile.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))).length
    ).toBeGreaterThan(2)
    expect(document.querySelector('img')).toBeNull()
  })
})

function homeProjectNavigationTests(): void {
  it('greets the user and lists the active team’s projects as rows', () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByText('Welcome back, Maya')).toBeInTheDocument()
    expect(screen.getByTestId('team-name')).toHaveTextContent('Strider')
    const list = screen.getByTestId('project-list')
    expect(within(list).getByText('Rover MK2')).toBeInTheDocument()
    expect(within(list).getByText('Arm')).toBeInTheDocument()
    expect(within(list).getByText('six-wheel rover')).toBeInTheDocument()
  })

  it('shows each row its OWN latest activity, and honest emptiness for the rest', () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(within(row('p1')).getByText(/created the project/)).toBeInTheDocument()
    expect(within(row('p2')).queryByText(/created the project/)).toBeNull()
    expect(within(row('p2')).getByText('No recent activity.')).toBeInTheDocument()
  })

  it('asks for a selection while no project is current', () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(within(pane()).getByText(/select a project on the left/i)).toBeInTheDocument()
  })

  it('selecting a row makes it current and stays on Home — nothing opens', async () => {
    mockHome()
    useWorkspaceStore.setState({ project: ROVER })
    const onOpenProject = vi.fn()
    render(<HomeScreen onOpenProject={onOpenProject} />)
    expect(row('p1')).toHaveAttribute('aria-current', 'true')
    expect(row('p2')).not.toHaveAttribute('aria-current')
    await userEvent.click(screen.getByRole('button', { name: 'Select Arm' }))
    expect(onOpenProject).not.toHaveBeenCalled()
    expect(useWorkspaceStore.getState().project).toEqual({ id: 'p2', name: 'Arm', teamId: 't1' })
    expect(row('p2')).toHaveAttribute('aria-current', 'true')
    expect(within(pane()).getByRole('heading', { name: 'Arm' })).toBeInTheDocument()
  })

  it('selecting a row from another view returns the pane to the project', async () => {
    mockHome()
    useWorkspaceStore.setState({ project: ROVER })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await showMembers()
    await userEvent.click(screen.getByRole('button', { name: 'Select Arm' }))
    expect(within(pane()).getByRole('heading', { name: 'Arm' })).toBeInTheDocument()
  })

  it('opens the current project (with its team) from the pane', async () => {
    mockHome()
    useWorkspaceStore.setState({ project: ROVER })
    const onOpenProject = vi.fn()
    render(<HomeScreen onOpenProject={onOpenProject} />)
    await userEvent.click(within(pane()).getByRole('button', { name: 'Open workspace' }))
    expect(onOpenProject).toHaveBeenCalledWith(ROVER)
  })

  it('goes to Live Bench for the current project', async () => {
    mockHome()
    useWorkspaceStore.setState({ project: ROVER })
    const onNavigate = vi.fn()
    render(<HomeScreen onOpenProject={vi.fn()} onNavigate={onNavigate} />)
    await userEvent.click(within(pane()).getByRole('button', { name: 'Live Bench' }))
    expect(onNavigate).toHaveBeenCalledWith('bench')
  })
}

function homeTeamProjectContextTests(): void {
  it("carries the current project's setup list and recent rail in Overview", () => {
    mockHome()
    useWorkspaceStore.setState({ project: ROVER })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    const p = pane()
    expect(within(p).getByRole('tab', { name: 'Overview' })).toHaveAttribute(
      'aria-selected',
      'true'
    )
    expect(within(p).getByText('PROJECT SETUP')).toBeInTheDocument()
    expect(within(p).getByText('ON THIS COMPUTER')).toBeInTheDocument()
    // .solus is summarised here; the full card lives on its own tab.
    expect(within(p).getByRole('button', { name: 'Add instructions' })).toBeInTheDocument()
    expect(within(p).getByText('RECENT')).toBeInTheDocument()
    // Not under the desktop bridge here, so the card degrades to its honest note.
    expect(within(p).getByText(/available in the Solus desktop app/)).toBeInTheDocument()
    expect(within(p).getByTestId('project-sources')).toBeInTheDocument()
    expect(within(p).getByText(/created the project/)).toBeInTheDocument()
  })

  it('switches the active team from the selector', async () => {
    const home = mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /switch team/i }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: /maya/i }))
    expect(home.actions.switchTeam).toHaveBeenCalledWith('t-me')
  })

  it('hides the team selector with a single team', () => {
    mockHome({ teams: [TEAM] })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.queryByRole('button', { name: /switch team/i })).toBeNull()
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

  it('opens the project’s own full activity in the Activity tab', async () => {
    mockHome()
    useWorkspaceStore.setState({ project: { id: 'p2', name: 'Arm', teamId: 't1' } })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(within(pane()).getByRole('button', { name: /all activity/i }))
    expect(vi.mocked(projectActivity.useProjectActivity)).toHaveBeenCalledWith('t1', 'p2')
    const panel = within(pane()).getByRole('tabpanel')
    expect(within(panel).getByText(/created the project/)).toBeInTheDocument()
  })

  it('keeps the account card in the sidebar with the team’s status', () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} />)
    const sidebar = screen.getByRole('complementary', { name: 'Projects' })
    expect(within(sidebar).getByText('Welcome back, Maya')).toBeInTheDocument()
    expect(within(sidebar).getByText('2 MEMBERS')).toBeInTheDocument()
  })
}

function homeProjectManagementTests(): void {
  it('edits a project’s name and description through the row menu', async () => {
    const home = mockHome()
    vi.mocked(home.actions.editProject).mockResolvedValue(true)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Project actions for Rover MK2' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Edit details' }))
    const name = screen.getByRole('textbox', { name: 'Project name' })
    await userEvent.clear(name)
    await userEvent.type(name, 'Rover MK3')
    await userEvent.type(screen.getByRole('textbox', { name: 'Description' }), ' with a lidar')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(home.actions.editProject).toHaveBeenCalledWith(
      'p1',
      'Rover MK3',
      'six-wheel rover with a lidar'
    )
  })

  it('archives a project through the row menu — the menu never selects or opens it', async () => {
    const home = mockHome()
    vi.mocked(home.actions.archiveProject).mockResolvedValue(true)
    const onOpenProject = vi.fn()
    render(<HomeScreen onOpenProject={onOpenProject} />)
    await userEvent.click(screen.getByRole('button', { name: 'Project actions for Rover MK2' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Archive' }))
    expect(home.actions.archiveProject).toHaveBeenCalledWith('p1')
    expect(onOpenProject).not.toHaveBeenCalled()
    expect(useWorkspaceStore.getState().project).toBeNull()
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
}

function homeProjectManagementPermissionsTests(): void {
  it('keeps archived projects out of the list, behind a collapsed count, with unarchive and delete', async () => {
    const home = mockHome({
      projects: [PROJECT, { ...ARM, archived_at: '2026-07-01T00:00:00Z' }]
    })
    vi.mocked(home.actions.unarchiveProject).mockResolvedValue(true)
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(within(screen.getByTestId('project-list')).queryByText('Arm')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Unarchive Arm' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /archived \(1\)/i }))
    expect(screen.getByRole('button', { name: 'Delete Arm' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Unarchive Arm' }))
    expect(home.actions.unarchiveProject).toHaveBeenCalledWith('p2')
  })

  it('hides management actions and new project for viewers', () => {
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
}

function homeTeamMembershipTests(): void {
  it('shows the active team with its member count, roster with roles, and the team feed', async () => {
    mockHome()
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(screen.getByTestId('team-name')).toHaveTextContent('Strider')
    expect(screen.getByText('2 members')).toBeInTheDocument()
    expect(screen.queryByText('bob@strider.dev')).toBeNull()
    await showMembers()
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
    await showMembers()
    expect(screen.queryByLabelText('Role for bob@strider.dev')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Invite' })).toBeNull()
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
    await showMembers()
    await userEvent.click(screen.getByRole('button', { name: 'Invite' }))
    await userEvent.type(screen.getByLabelText('Teammate email'), 'eve@strider.dev')
    await userEvent.click(screen.getByRole('button', { name: 'Send invite' }))
    expect(await screen.findByTestId('invite-token')).toHaveTextContent('tok-once')
    expect(team.actions.invite).toHaveBeenCalledWith('eve@strider.dev')
  })
}

function homeTeamLimitsAndAvailabilityTests(): void {
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
    await teamMenuPick(/new team/i)
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
}

describe('HomeScreen — linked repos under project names', () => {
  it('shows each project’s repo, the current one from its live sources', () => {
    mockHome()
    useWorkspaceStore.setState({ project: ROVER })
    vi.mocked(projectRepos.useProjectRepos).mockReturnValue({
      p1: [{ provider: 'github', repo: 'stale/old-name' }],
      p2: [{ provider: 'github', repo: 'strider/arm-fw' }]
    })
    vi.mocked(projectSources.useProjectSources).mockReturnValue({
      status: 'ready',
      sources: [
        {
          id: 's1',
          project_id: 'p1',
          type: 'github',
          name: 'n',
          status: 'connected',
          config: { repo: 'strider/rover-fw' },
          account_login: null,
          last_synced_at: null,
          last_error: null,
          created_at: '',
          updated_at: ''
        }
      ],
      actions: { refresh: vi.fn(), syncNow: vi.fn(), disconnect: vi.fn() }
    })
    render(<HomeScreen onOpenProject={vi.fn()} />)
    expect(within(row('p1')).getByText('strider/rover-fw')).toBeInTheDocument()
    expect(within(row('p1')).queryByText('stale/old-name')).toBeNull()
    expect(within(row('p2')).getByText('strider/arm-fw')).toBeInTheDocument()
    // The pane's header names the current project's repo too.
    expect(within(pane()).getByText('strider/rover-fw')).toBeInTheDocument()
    expect(projectRepos.useProjectRepos).toHaveBeenCalledWith(['p1', 'p2'])
  })

  describe('HomeScreen — motion', () => {
    it('fades the pane in, keyed to what it shows', async () => {
      mockHome()
      useWorkspaceStore.setState({ project: ROVER })
      render(<HomeScreen onOpenProject={vi.fn()} />)
      const before = pane().firstElementChild as HTMLElement
      expect(before).toHaveClass('home-pane-in')
      await showMembers()
      expect(pane().firstElementChild).not.toBe(before)
      expect(pane().firstElementChild).toHaveClass('home-pane-in')
    })
  })
})
