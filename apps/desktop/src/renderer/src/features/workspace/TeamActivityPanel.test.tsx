// SOLUSDEV-244 / HOME H5: the team's humanised feed on Home — six rows, actor
// attribution, honest view-all with the server total (activity-feed.md).
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ActivityApi, TeamMemberApi } from '../../lib/api/resources'
import { TeamActivityPanel } from './TeamActivityPanel'

const MEMBERS: TeamMemberApi[] = [
  { user_id: 'u1', email: 'maya@strider.dev', name: 'Maya', role: 'owner', joined_at: '' }
]
const row = (i: number): ActivityApi => ({
  id: `a${i}`,
  type: 'project.created',
  domain: null,
  actor_id: 'u1',
  project_id: 'p1',
  payload: { name: `P${i}` },
  created_at: '2026-07-06T00:00:00Z'
})

describe('TeamActivityPanel', () => {
  it('humanises rows with the actor and shows an honest empty state', () => {
    const { unmount } = render(
      <TeamActivityPanel
        activity={[row(1)]}
        members={MEMBERS}
        total={1}
        hasMore={false}
        onLoadMore={vi.fn()}
      />
    )
    expect(screen.getByText('Maya')).toBeInTheDocument()
    expect(screen.getByText(/created the project/)).toBeInTheDocument()
    unmount()
    render(
      <TeamActivityPanel
        activity={[]}
        members={MEMBERS}
        total={0}
        hasMore={false}
        onLoadMore={vi.fn()}
      />
    )
    expect(screen.getByText(/No activity yet/)).toBeInTheDocument()
  })

  it('previews six rows and opens the full dialog with the server total', async () => {
    const rows = Array.from({ length: 8 }, (_, i) => row(i))
    render(
      <TeamActivityPanel
        activity={rows}
        members={MEMBERS}
        total={40}
        hasMore
        onLoadMore={vi.fn()}
      />
    )
    expect(screen.getAllByText(/created the project/)).toHaveLength(6)
    await userEvent.click(screen.getByRole('button', { name: /view all activity/i }))
    expect(screen.getByRole('dialog', { name: 'All activity' })).toBeInTheDocument()
    expect(screen.getByText('40 EVENTS')).toBeInTheDocument()
  })

  it('renders a hostile payload as literal text', () => {
    render(
      <TeamActivityPanel
        activity={[{ ...row(1), payload: { name: '<img src=x onerror=alert(1)>' } }]}
        members={MEMBERS}
        total={1}
        hasMore={false}
        onLoadMore={vi.fn()}
      />
    )
    expect(screen.getByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
  })
})
