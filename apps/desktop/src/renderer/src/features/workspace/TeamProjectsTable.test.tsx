// SOLUSDEV-319 (multi-team Home, design D): the active team's projects as a table — name and
// description, its linked repos, the last change — each row opening the project's pane; the ⋯,
// New project and the archived section keep their role gating.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ActivityApi, Project, TeamSummary } from '../../lib/api/resources'
import type { HomeActions } from './useHomeData'
import { TeamProjectsTable, type TeamProjectsTableProps } from './TeamProjectsTable'

const TEAM: TeamSummary = {
  team_id: 't-arm',
  name: 'Arm Lab',
  role: 'member',
  is_personal: false,
  plan_status: 'active',
  trial_ends_at: ''
}
const ARM: Project = {
  id: 'p-arm',
  team_id: 't-arm',
  name: 'lerobot so101',
  description: 'Six-axis arm',
  archived_at: null,
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z'
}
const CHARGER: Project = { ...ARM, id: 'p-usb', name: 'USB Charger Lab', description: null }
const OLD: Project = { ...ARM, id: 'p-old', name: 'Old rig', archived_at: '2026-09-01T00:00:00Z' }
const SYNCED: ActivityApi = {
  id: 'a1',
  type: 'source.synced',
  domain: null,
  actor_id: 'u1',
  project_id: 'p-arm',
  payload: {},
  created_at: new Date(Date.now() - 2 * 3600_000).toISOString()
} as unknown as ActivityApi

function actions(): HomeActions {
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
  } as unknown as HomeActions
}

function props(overrides: Partial<TeamProjectsTableProps> = {}): TeamProjectsTableProps {
  return {
    team: TEAM,
    projects: [ARM, CHARGER, OLD],
    activityByProject: { 'p-arm': [SYNCED] },
    reposByProject: { 'p-arm': [{ provider: 'github', repo: 'mehdihdev/lerobot-arm' }] } as never,
    actions: actions(),
    onSelect: vi.fn(),
    onNewProject: vi.fn(),
    onActionFailed: vi.fn(),
    ...overrides
  }
}

const table = (): HTMLElement => screen.getByRole('table', { name: 'Projects in Arm Lab' })

describe('TeamProjectsTable', () => {
  it('shows each live project with its repo and last change; archived ones apart', () => {
    render(<TeamProjectsTable {...props()} />)
    const rows = within(table()).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('lerobot so101')
    expect(rows[0]).toHaveTextContent('Six-axis arm')
    expect(rows[0]).toHaveTextContent('mehdihdev/lerobot-arm')
    expect(rows[0]).toHaveTextContent('2h ago')
    expect(rows[1]).toHaveTextContent('USB Charger Lab')
    expect(rows[1]).toHaveTextContent('No recent activity')
    expect(within(table()).queryByText('Old rig')).toBeNull()
    expect(screen.getByText(/archived/i)).toBeInTheDocument()
  })

  it('counts the live projects in its heading', () => {
    render(<TeamProjectsTable {...props()} />)
    expect(screen.getByText('PROJECTS · 2')).toBeInTheDocument()
  })

  it('opens a project from its name', async () => {
    const p = props()
    render(<TeamProjectsTable {...p} />)
    await userEvent.click(screen.getByRole('button', { name: 'Open lerobot so101' }))
    expect(p.onSelect).toHaveBeenCalledWith(ARM)
  })

  it('offers New project and the row menu to members, neither to viewers', async () => {
    const p = props()
    const first = render(<TeamProjectsTable {...p} />)
    await userEvent.click(screen.getByRole('button', { name: 'New project' }))
    expect(p.onNewProject).toHaveBeenCalled()
    expect(within(table()).getAllByRole('button', { name: /Project actions for/ }).length).toBe(2)
    first.unmount()

    render(<TeamProjectsTable {...props({ team: { ...TEAM, role: 'viewer' } })} />)
    expect(screen.queryByRole('button', { name: 'New project' })).toBeNull()
    expect(within(table()).queryAllByRole('button', { name: /Project actions for/ })).toHaveLength(
      0
    )
  })

  it('says what to do when the team has no projects yet', () => {
    const { unmount } = render(<TeamProjectsTable {...props({ projects: [] })} />)
    expect(screen.getByText('Create one to start building the graph.')).toBeInTheDocument()
    unmount()
    render(<TeamProjectsTable {...props({ projects: [], team: { ...TEAM, role: 'viewer' } })} />)
    expect(screen.getByText('No projects in this team yet.')).toBeInTheDocument()
  })
})
