// Home's project list (SOLUSDEV-317): rows, selection, the current marker,
// role gating, and honest emptiness.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HomeProjectList, type HomeProjectListProps } from './HomeProjectList'
import type { ActivityApi, Project, TeamSummary } from '../../lib/api/resources'
import type { HomeActions } from './useHomeData'

const TEAM: TeamSummary = {
  team_id: 't1',
  name: 'Strider',
  role: 'owner',
  is_personal: false,
  plan_status: 'trial',
  trial_ends_at: ''
}
const ROVER: Project = {
  id: 'p1',
  team_id: 't1',
  name: 'Rover MK2',
  description: 'six-wheel rover',
  archived_at: null,
  created_at: '',
  updated_at: ''
}
const ARM: Project = { ...ROVER, id: 'p2', name: 'Arm', description: null }
const ROW: ActivityApi = {
  id: 'a1',
  type: 'project.created',
  domain: null,
  actor_id: 'u1',
  project_id: 'p1',
  payload: { name: 'Rover MK2' },
  created_at: '2026-07-06T00:00:00Z'
}

function setup(overrides: Partial<HomeProjectListProps> = {}): HomeProjectListProps {
  const props: HomeProjectListProps = {
    team: TEAM,
    projects: [ROVER, ARM],
    activityByProject: { p1: [ROW] },
    currentProjectId: null,
    actions: {
      archiveProject: vi.fn(),
      unarchiveProject: vi.fn(),
      deleteProject: vi.fn(),
      editProject: vi.fn()
    } as unknown as HomeActions,
    reposByProject: { p1: [{ provider: 'github', repo: 'mehdihdev/lerobot-arm' }] },
    onSelect: vi.fn(),
    onNewProject: vi.fn(),
    onActionFailed: vi.fn(),
    ...overrides
  }
  render(<HomeProjectList {...props} />)
  return props
}

describe('HomeProjectList', () => {
  it('lists live projects with their count, description and latest activity', () => {
    setup()
    expect(screen.getByText('PROJECTS · 2')).toBeInTheDocument()
    const rover = screen.getByTestId('project-row-p1')
    expect(within(rover).getByText('six-wheel rover')).toBeInTheDocument()
    expect(within(rover).getByText(/created the project/)).toBeInTheDocument()
    expect(
      within(screen.getByTestId('project-row-p2')).getByText('No recent activity.')
    ).toBeInTheDocument()
  })

  it('marks only the current project', () => {
    setup({ currentProjectId: 'p2' })
    expect(screen.getByTestId('project-row-p2')).toHaveAttribute('aria-current', 'true')
    expect(screen.getByTestId('project-row-p1')).not.toHaveAttribute('aria-current')
  })

  it('selects a project from its row', async () => {
    const props = setup()
    await userEvent.click(screen.getByRole('button', { name: 'Select Arm' }))
    expect(props.onSelect).toHaveBeenCalledWith(ARM)
  })

  it('opening the row menu never selects the row', async () => {
    const props = setup()
    await userEvent.click(screen.getByRole('button', { name: 'Project actions for Rover MK2' }))
    expect(screen.getByRole('menuitem', { name: 'Delete' })).toBeInTheDocument()
    expect(props.onSelect).not.toHaveBeenCalled()
  })

  it('offers New project to members and up', async () => {
    const props = setup({ team: { ...TEAM, role: 'member' } })
    await userEvent.click(screen.getByRole('button', { name: 'New project' }))
    expect(props.onNewProject).toHaveBeenCalled()
  })

  it('gives viewers no menu, no New project, and a viewer-worded empty state', () => {
    setup({ team: { ...TEAM, role: 'viewer' }, projects: [] })
    expect(screen.queryByRole('button', { name: 'New project' })).toBeNull()
    expect(screen.getByText('No projects in this team yet.')).toBeInTheDocument()
  })

  it('keeps archived projects out of the live rows', () => {
    setup({ projects: [ROVER, { ...ARM, archived_at: '2026-07-01T00:00:00Z' }] })
    expect(screen.getByText('PROJECTS · 1')).toBeInTheDocument()
    expect(screen.queryByTestId('project-row-p2')).toBeNull()
    expect(screen.getByRole('button', { name: /archived \(1\)/i })).toBeInTheDocument()
  })

  it('shows the linked repo with its provider logo under the name, and nothing for others', () => {
    setup()
    const rover = screen.getByTestId('project-row-p1')
    expect(within(rover).getByText('mehdihdev/lerobot-arm')).toBeInTheDocument()
    expect(within(rover).getByTestId('repo-logo-github')).toBeInTheDocument()
    expect(within(screen.getByTestId('project-row-p2')).queryByTestId(/^repo-logo-/)).toBeNull()
  })

  it('counts further repos after the first', () => {
    setup({
      reposByProject: {
        p1: [
          { provider: 'github', repo: 'org/a' },
          { provider: 'github', repo: 'org/b' }
        ]
      }
    })
    expect(within(screen.getByTestId('project-row-p1')).getByText('+1')).toBeInTheDocument()
  })

  it('makes the whole card the select target, with the menu beside it, not inside', () => {
    setup()
    const select = screen.getByRole('button', { name: 'Select Rover MK2' })
    const menu = screen.getByRole('button', { name: 'Project actions for Rover MK2' })
    expect(select).toHaveStyle({ width: '100%' })
    expect(select.contains(menu)).toBe(false)
    expect(screen.getByTestId('project-row-p1')).toContainElement(menu)
  })

  it('staggers rows in, and eases the card itself', () => {
    setup()
    const rows = [screen.getByTestId('project-row-p1'), screen.getByTestId('project-row-p2')]
    expect(rows[0]).toHaveClass('home-row-in')
    expect(rows[0].style.animationDelay).toBe('0ms')
    expect(rows[1].style.animationDelay).not.toBe('0ms')
    expect(screen.getByRole('button', { name: 'Select Rover MK2' })).toHaveClass('home-card')
  })
})
