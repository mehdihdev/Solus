// One project's activity, inline in Home's Activity tab (SOLUSDEV-317):
// server-filtered rows, the project's own total, paging, honest states.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectActivityFeed } from './ProjectActivityFeed'
import * as projectActivity from './useProjectActivity'
import type { ActivityApi } from '../../lib/api/resources'

vi.mock('./useProjectActivity', () => ({ useProjectActivity: vi.fn() }))

const ROW: ActivityApi = {
  id: 'a1',
  type: 'project.created',
  domain: null,
  actor_id: 'u1',
  project_id: 'p1',
  payload: { name: '<b>Rover</b>' },
  created_at: '2026-07-06T00:00:00Z'
}
const PROJECT = { id: 'p1', name: 'Rover MK2', teamId: 't1' }

function mockFeed(over: Partial<projectActivity.ProjectActivityData> = {}): void {
  vi.mocked(projectActivity.useProjectActivity).mockReturnValue({
    status: 'ready',
    activity: [ROW],
    total: 1,
    hasMore: false,
    loadMore: vi.fn(),
    ...over
  })
}

beforeEach(() => vi.clearAllMocks())

describe('ProjectActivityFeed', () => {
  it("asks the server for this project's rows and shows its total, as text", () => {
    mockFeed()
    const { container } = render(<ProjectActivityFeed project={PROJECT} />)
    expect(projectActivity.useProjectActivity).toHaveBeenCalledWith('t1', 'p1')
    expect(screen.getByText('1 EVENT')).toBeInTheDocument()
    expect(screen.getByText(/created the project/)).toBeInTheDocument()
    expect(container.querySelector('b')).toBeNull()
  })

  it('pages with Load more while the server has more', async () => {
    const loadMore = vi.fn().mockResolvedValue(undefined)
    mockFeed({ total: 9, hasMore: true, loadMore })
    render(<ProjectActivityFeed project={PROJECT} />)
    await userEvent.click(screen.getByRole('button', { name: 'Load more' }))
    expect(loadMore).toHaveBeenCalled()
  })

  it('is honest while loading, offline and empty', () => {
    mockFeed({ status: 'loading', activity: [] })
    const first = render(<ProjectActivityFeed project={PROJECT} />)
    expect(screen.getByText(/loading activity/i)).toBeInTheDocument()
    first.unmount()
    mockFeed({ status: 'offline', activity: [] })
    const second = render(<ProjectActivityFeed project={PROJECT} />)
    expect(screen.getByText(/couldn't load this project's activity/i)).toBeInTheDocument()
    second.unmount()
    mockFeed({ activity: [], total: 0 })
    render(<ProjectActivityFeed project={PROJECT} />)
    expect(screen.getByText('No activity yet.')).toBeInTheDocument()
  })
})
