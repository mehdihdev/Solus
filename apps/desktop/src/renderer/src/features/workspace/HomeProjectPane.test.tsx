// Home's project pane (SOLUSDEV-317): header actions, the Overview / .solus
// tabs, the current project's recent activity and its full-activity dialog.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HomeProjectPane, type HomeProjectPaneProps } from './HomeProjectPane'
import * as projectActivity from './useProjectActivity'
import type { ActivityApi } from '../../lib/api/resources'

vi.mock('./useProjectActivity', () => ({ useProjectActivity: vi.fn() }))
vi.mock('./ProjectSourcesSummary', () => ({
  ProjectSourcesSummary: ({ limit, onAdd }: { limit?: number; onAdd: () => void }) => (
    <button type="button" data-testid="sources" data-limit={String(limit ?? 'all')} onClick={onAdd}>
      sources-summary
    </button>
  )
}))
vi.mock('./SolusCard', () => ({
  SolusCard: ({ projectId }: { projectId: string | null }) => (
    <div data-testid="solus-card" data-project={projectId ?? ''} />
  )
}))
vi.mock('../project/ProjectFolderCard', () => ({
  ProjectFolderCard: ({ projectId, compact }: { projectId: string; compact?: boolean }) => (
    <div data-testid="folder-card" data-project={projectId} data-compact={String(!!compact)} />
  )
}))

const ROW: ActivityApi = {
  id: 'a1',
  type: 'project.created',
  domain: null,
  actor_id: 'u1',
  project_id: 'p1',
  payload: { name: 'Rover MK2' },
  created_at: '2026-07-06T00:00:00Z'
}

function setup(overrides: Partial<HomeProjectPaneProps> = {}): HomeProjectPaneProps {
  const props: HomeProjectPaneProps = {
    project: { id: 'p1', name: 'Rover MK2', teamId: 't1' },
    description: 'six-wheel rover',
    activity: [ROW],
    repos: [{ provider: 'github', repo: 'mehdihdev/elegoo_robot' }],
    onOpen: vi.fn(),
    onBench: vi.fn(),
    onManageSources: vi.fn(),
    ...overrides
  }
  render(<HomeProjectPane {...props} />)
  return props
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(projectActivity.useProjectActivity).mockReturnValue({
    status: 'ready',
    activity: [ROW],
    total: 1,
    hasMore: false,
    loadMore: vi.fn()
  })
})

const tab = (name: string): HTMLElement => screen.getByRole('tab', { name })

describe('HomeProjectPane', () => {
  it('names the project and wires Open workspace and Live Bench', async () => {
    const props = setup()
    expect(screen.getByRole('heading', { name: 'Rover MK2' })).toBeInTheDocument()
    expect(screen.getByText('six-wheel rover')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Open workspace' }))
    expect(props.onOpen).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Live Bench' }))
    expect(props.onBench).toHaveBeenCalled()
  })

  it('offers four tabs and opens on Overview', () => {
    setup()
    const names = screen.getAllByRole('tab').map((t) => t.textContent)
    expect(names).toEqual(['Overview', 'Sources', '.solus', 'Activity'])
    expect(tab('Overview')).toHaveAttribute('aria-selected', 'true')
  })

  it('Overview: compact folder, a few sources, .solus and recent activity', async () => {
    const props = setup()
    expect(screen.getByTestId('folder-card')).toHaveAttribute('data-compact', 'true')
    expect(screen.getByTestId('sources')).toHaveAttribute('data-limit', '4')
    expect(screen.getByTestId('solus-card')).toHaveAttribute('data-project', 'p1')
    expect(screen.getByText('RECENT IN THIS PROJECT')).toBeInTheDocument()
    expect(screen.getByText(/created the project/)).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('sources'))
    expect(props.onManageSources).toHaveBeenCalled()
  })

  it('says so when the project has no recent activity', () => {
    setup({ activity: [] })
    expect(screen.getByText('No recent activity.')).toBeInTheDocument()
  })

  it('Sources: the full folder card and every source', async () => {
    setup()
    await userEvent.click(tab('Sources'))
    expect(tab('Sources')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('folder-card')).toHaveAttribute('data-compact', 'false')
    expect(screen.getByTestId('sources')).toHaveAttribute('data-limit', 'all')
    expect(screen.queryByTestId('solus-card')).toBeNull()
  })

  it('.solus: the card on its own', async () => {
    setup()
    await userEvent.click(tab('.solus'))
    expect(screen.getByTestId('solus-card')).toHaveAttribute('data-project', 'p1')
    expect(screen.queryByTestId('folder-card')).toBeNull()
  })

  it('All activity opens the Activity tab with the project’s own feed and paging', async () => {
    const loadMore = vi.fn()
    vi.mocked(projectActivity.useProjectActivity).mockReturnValue({
      status: 'ready',
      activity: [ROW],
      total: 9,
      hasMore: true,
      loadMore
    })
    setup()
    await userEvent.click(screen.getByRole('button', { name: /all activity/i }))
    expect(tab('Activity')).toHaveAttribute('aria-selected', 'true')
    expect(projectActivity.useProjectActivity).toHaveBeenCalledWith('t1', 'p1')
    const panel = screen.getByRole('tabpanel')
    expect(within(panel).getByText(/created the project/)).toBeInTheDocument()
    expect(within(panel).getByText('9 EVENTS')).toBeInTheDocument()
    await userEvent.click(within(panel).getByRole('button', { name: 'Load more' }))
    expect(loadMore).toHaveBeenCalled()
  })

  it('the Activity tab is honest while loading and offline', async () => {
    vi.mocked(projectActivity.useProjectActivity).mockReturnValue({
      status: 'offline',
      activity: [],
      total: 0,
      hasMore: false,
      loadMore: vi.fn()
    })
    setup()
    await userEvent.click(tab('Activity'))
    expect(screen.getByText(/couldn't load this project's activity/i)).toBeInTheDocument()
  })

  it('wires tabs to their panel and moves between them with the arrow keys', async () => {
    setup()
    const overview = tab('Overview')
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', overview.id)
    expect(overview).toHaveAttribute('aria-controls', screen.getByRole('tabpanel').id)
    expect(tab('Sources')).toHaveAttribute('tabindex', '-1')
    overview.focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(tab('Sources')).toHaveAttribute('aria-selected', 'true')
    expect(tab('Sources')).toHaveFocus()
    await userEvent.keyboard('{ArrowLeft}{ArrowLeft}')
    expect(tab('Activity')).toHaveAttribute('aria-selected', 'true')
  })

  it('names the linked repo under the project title', () => {
    setup()
    const heading = screen.getByRole('heading', { name: 'Rover MK2' })
    const line = screen.getByText('mehdihdev/elegoo_robot')
    expect(heading.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByTestId('repo-logo-github')).toBeInTheDocument()
  })

  it('shows no repo line for a project without one', () => {
    setup({ repos: [] })
    expect(screen.queryByTestId(/^repo-logo-/)).toBeNull()
  })
})
