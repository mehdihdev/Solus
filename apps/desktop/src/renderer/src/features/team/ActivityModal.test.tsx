// SOLUSDEV-233: the full-feed activity dialog + "View all activity" affordance
// shared by the Team and Home activity panels.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ActivityModal, ViewAllActivityButton } from './ActivityModal'
import type { ActivityApi, TeamMemberApi } from '../../lib/api/resources'

const MEMBERS: TeamMemberApi[] = [
  {
    user_id: 'u1',
    email: 'maya@example.dev',
    name: 'Maya K',
    role: 'owner',
    joined_at: '2026-07-01T00:00:00Z'
  }
]

function item(id: string): ActivityApi {
  return {
    id,
    type: 'invite.accepted',
    domain: null,
    actor_id: 'u1',
    project_id: null,
    payload: {},
    created_at: '2026-07-06T00:00:00Z'
  }
}

describe('ActivityModal', () => {
  it('renders every loaded row, the server total, and actor attribution', () => {
    render(
      <ActivityModal
        activity={[item('a1'), item('a2'), item('a3')]}
        total={12}
        members={MEMBERS}
        onClose={vi.fn()}
      />
    )
    const dialog = screen.getByRole('dialog', { name: 'All activity' })
    expect(dialog).toBeInTheDocument()
    expect(screen.getAllByText(/joined the team/)).toHaveLength(3)
    expect(screen.getAllByText('Maya K')).toHaveLength(3)
    expect(screen.getByText(/12 EVENTS/)).toBeInTheDocument()
  })

  it('renders plain rows without a roster (cross-team feed)', () => {
    render(<ActivityModal activity={[item('a1')]} total={1} onClose={vi.fn()} />)
    expect(screen.getByText(/joined the team/)).toBeInTheDocument()
    expect(screen.queryByText('Maya K')).not.toBeInTheDocument()
  })

  it('pages further via Load more only while the server has more', async () => {
    const onLoadMore = vi.fn(async () => undefined)
    const { rerender } = render(
      <ActivityModal
        activity={[item('a1')]}
        total={2}
        hasMore
        onLoadMore={onLoadMore}
        onClose={vi.fn()}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: 'Load more' }))
    expect(onLoadMore).toHaveBeenCalledTimes(1)
    rerender(
      <ActivityModal
        activity={[item('a1'), item('a2')]}
        total={2}
        hasMore={false}
        onLoadMore={onLoadMore}
        onClose={vi.fn()}
      />
    )
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })

  it('renders hostile payload text as literal text, never as HTML', () => {
    const hostile: ActivityApi = {
      ...item('a1'),
      type: 'project.created',
      payload: { name: '<img src=x onerror="alert(1)">' }
    }
    const { container } = render(<ActivityModal activity={[hostile]} total={1} onClose={vi.fn()} />)
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText(/<img src=x onerror="alert\(1\)">/)).toBeInTheDocument()
  })

  it('says honestly when it shows fewer rows than the total and cannot page', () => {
    render(<ActivityModal activity={[item('a1'), item('a2')]} total={20} onClose={vi.fn()} />)
    expect(screen.getByText(/most recent 2 of 20/)).toBeInTheDocument()
  })

  it('shows no truncation note while paging is offered or the feed is complete', () => {
    const { rerender } = render(
      <ActivityModal
        activity={[item('a1')]}
        total={20}
        hasMore
        onLoadMore={vi.fn(async () => undefined)}
        onClose={vi.fn()}
      />
    )
    expect(screen.queryByText(/most recent/)).not.toBeInTheDocument()
    rerender(<ActivityModal activity={[item('a1'), item('a2')]} total={2} onClose={vi.fn()} />)
    expect(screen.queryByText(/most recent/)).not.toBeInTheDocument()
  })

  it('closes from the explicit close button', async () => {
    const onClose = vi.fn()
    render(<ActivityModal activity={[item('a1')]} total={1} onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalled()
  })
})

describe('ViewAllActivityButton', () => {
  it('shows the total and fires onClick', async () => {
    const onClick = vi.fn()
    render(<ViewAllActivityButton total={12} onClick={onClick} />)
    await userEvent.click(screen.getByRole('button', { name: /View all activity \(12\)/ }))
    expect(onClick).toHaveBeenCalled()
  })
})
