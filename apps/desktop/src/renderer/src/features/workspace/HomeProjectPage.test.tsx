// SOLUSDEV-328 (design P2): Home's project page — the team's projects listed beside the current
// project (one click to switch, stay on the page), the project's folder + sources and its .solus
// side by side with no tabs, and its activity as a full-height column when wide, below otherwise.
// Narrow, the list becomes a switcher in the header.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ActivityApi, Project, TeamSummary } from '../../lib/api/resources'
import { HomeProjectPage, type HomeProjectPageProps } from './HomeProjectPage'

vi.mock('./ProjectSourcesSummary', () => ({
  ProjectSourcesSummary: ({ onAdd }: { onAdd: () => void }) => (
    <button type="button" onClick={onAdd}>
      Add additional sources
    </button>
  )
}))
vi.mock('./SolusCard', () => ({
  SolusCard: ({ projectId }: { projectId: string | null }) => (
    <div data-testid="solus-card" data-project={projectId ?? ''} />
  )
}))
vi.mock('../project/ProjectFolderCard', () => ({
  ProjectFolderCard: ({ projectId }: { projectId: string }) => (
    <div data-testid="folder-card" data-project={projectId} />
  )
}))
vi.mock('./ProjectActivityFeed', () => ({
  ProjectActivityFeed: ({ project }: { project: { id: string } }) => (
    <div data-testid="project-activity" data-project={project.id} />
  )
}))

const TEAM: TeamSummary = {
  team_id: 't1',
  name: 'Strider',
  role: 'owner',
  is_personal: false,
  plan_status: 'active',
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
const OLD: Project = { ...ROVER, id: 'p3', name: 'Old rig', archived_at: '2026-09-01T00:00:00Z' }
const ROW = {
  id: 'a1',
  type: 'project.created',
  domain: null,
  actor_id: 'u1',
  project_id: 'p1',
  payload: { name: 'Rover MK2' },
  created_at: new Date(Date.now() - 2 * 3_600_000).toISOString()
} as unknown as ActivityApi

function setupProps(overrides: Partial<HomeProjectPageProps> = {}): HomeProjectPageProps {
  return {
    team: TEAM,
    projects: [ROVER, ARM, OLD],
    activityByProject: { p1: [ROW] },
    current: { id: 'p1', name: 'Rover MK2', teamId: 't1' },
    repos: [{ provider: 'github', repo: 'strider/rover-fw' }],
    onSelect: vi.fn(),
    onBack: vi.fn(),
    onNewProject: vi.fn(),
    onOpen: vi.fn(),
    onBench: vi.fn(),
    onManageSources: vi.fn(),
    layout: 'list',
    ...overrides
  }
}

function setup(overrides: Partial<HomeProjectPageProps> = {}): HomeProjectPageProps {
  const props = setupProps(overrides)
  render(<HomeProjectPage {...props} />)
  return props
}

beforeEach(() => vi.clearAllMocks())

describe('HomeProjectPage — the projects list', () => {
  it('lists the live projects with their last change, the current one marked', () => {
    setup()
    const list = screen.getByRole('list', { name: 'Projects in Strider' })
    const rows = within(list).getAllByRole('button')
    expect(rows.map((r) => r.getAttribute('aria-label'))).toEqual(['Show Rover MK2', 'Show Arm'])
    expect(rows[0]).toHaveAttribute('aria-current', 'true')
    expect(rows[0]).toHaveTextContent(/created the project/)
    expect(rows[1]).toHaveTextContent('No recent activity')
  })

  it('switches project in place on a click', async () => {
    const p = setup()
    await userEvent.click(screen.getByRole('button', { name: 'Show Arm' }))
    expect(p.onSelect).toHaveBeenCalledWith(ARM)
  })

  it('goes back to the team overview and offers New project to members and up', async () => {
    const p = setup()
    await userEvent.click(screen.getByRole('button', { name: 'Back to Strider' }))
    await userEvent.click(screen.getByRole('button', { name: 'New project' }))
    expect(p.onBack).toHaveBeenCalled()
    expect(p.onNewProject).toHaveBeenCalled()
  })

  it('offers viewers no New project', () => {
    setup({ team: { ...TEAM, role: 'viewer' } })
    expect(screen.queryByRole('button', { name: 'New project' })).toBeNull()
  })

  it('is a header switcher when narrow', async () => {
    const p = setup({ layout: 'narrow' })
    expect(screen.queryByRole('list', { name: 'Projects in Strider' })).toBeNull()
    const switcher = screen.getByRole('combobox', { name: 'Switch project' })
    expect(switcher).toHaveValue('p1')
    await userEvent.selectOptions(switcher, 'p2')
    expect(p.onSelect).toHaveBeenCalledWith(ARM)
    expect(screen.getAllByRole('button', { name: 'Back to Strider' })).toHaveLength(1)
  })
})

describe('HomeProjectPage — the project', () => {
  it('heads the project with its repo, description and two ways in', async () => {
    const p = setup()
    expect(screen.getByRole('heading', { level: 2, name: 'Rover MK2' })).toBeInTheDocument()
    expect(screen.getByText('strider/rover-fw')).toBeInTheDocument()
    expect(screen.getByText('six-wheel rover')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Live Bench' }))
    await userEvent.click(screen.getByRole('button', { name: 'Open workspace' }))
    expect(p.onBench).toHaveBeenCalled()
    expect(p.onOpen).toHaveBeenCalled()
  })

  it('shows folder, sources and .solus at once — no tabs', async () => {
    const p = setup()
    expect(screen.queryByRole('tablist')).toBeNull()
    expect(screen.getByTestId('folder-card')).toHaveAttribute('data-project', 'p1')
    expect(screen.getByTestId('solus-card')).toHaveAttribute('data-project', 'p1')
    await userEvent.click(screen.getByRole('button', { name: 'Add additional sources' }))
    expect(p.onManageSources).toHaveBeenCalled()
  })

  it('puts the activity in its own column when full, below the project otherwise', () => {
    setup({ layout: 'full' })
    const column = screen.getByTestId('project-page-activity')
    expect(within(column).getByTestId('project-activity')).toHaveAttribute('data-project', 'p1')
    expect(screen.getByTestId('project-page')).toHaveAttribute('data-layout', 'full')
  })

  it('keeps the activity under the project when not full', () => {
    setup({ layout: 'list' })
    expect(screen.queryByTestId('project-page-activity')).toBeNull()
    expect(
      within(screen.getByTestId('project-page-detail')).getByTestId('project-activity')
    ).toBeInTheDocument()
  })

  it('remounts the .solus card on a project switch, so an open composer never carries over', () => {
    const { rerender } = render(<HomeProjectPage {...setupProps()} />)
    const first = screen.getAllByTestId('solus-card').at(-1)
    rerender(
      <HomeProjectPage {...setupProps({ current: { id: 'p2', name: 'Arm', teamId: 't1' } })} />
    )
    const next = screen.getAllByTestId('solus-card').at(-1)
    expect(next).toHaveAttribute('data-project', 'p2')
    expect(next).not.toBe(first)
  })

  it('narrow: says "Pick a project" when the current one is not listed, and keeps New project', () => {
    setup({ layout: 'narrow', current: { id: 'p3', name: 'Old rig', teamId: 't1' } })
    const switcher = screen.getByRole('combobox', { name: 'Switch project' })
    expect(switcher).toHaveValue('')
    expect(within(switcher).getByRole('option', { name: 'Pick a project' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New project' })).toBeInTheDocument()
  })

  it('asks for a pick when no project of this team is current, list still there', () => {
    setup({ current: null })
    expect(screen.getByText('Pick a project to see its folder, sources and .solus.')).toBeVisible()
    expect(screen.getByRole('list', { name: 'Projects in Strider' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Open workspace' })).toBeNull()
  })
})
