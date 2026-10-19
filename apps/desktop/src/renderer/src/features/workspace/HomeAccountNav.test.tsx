// Home's ACCOUNT nav (SOLUSDEV-317): the two rows that swap the pane to the
// Members or Connected accounts view, with the pressed state.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HomeAccountNav } from './HomeAccountNav'

describe('HomeAccountNav', () => {
  it('marks the active view', () => {
    render(<HomeAccountNav view="members" team={null} accounts={null} onShow={vi.fn()} />)
    expect(screen.getByRole('button', { name: /^team & invites/i })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
    expect(screen.getByRole('button', { name: /^connected accounts/i })).toHaveAttribute(
      'aria-pressed',
      'false'
    )
  })

  it('states the team: just you, or members and pending invites', () => {
    const { unmount } = render(
      <HomeAccountNav
        view="project"
        team={{ members: 1, pending: 0 }}
        accounts={null}
        onShow={vi.fn()}
      />
    )
    expect(screen.getByText('JUST YOU')).toBeInTheDocument()
    unmount()
    render(
      <HomeAccountNav
        view="project"
        team={{ members: 3, pending: 1 }}
        accounts={null}
        onShow={vi.fn()}
      />
    )
    expect(screen.getByText('3 MEMBERS · 1 PENDING')).toBeInTheDocument()
  })

  it('states account health, flags attention, and says nothing while unknown', () => {
    const { unmount } = render(
      <HomeAccountNav
        view="project"
        team={null}
        accounts={{ healthy: 1, attention: 0 }}
        onShow={vi.fn()}
      />
    )
    expect(screen.getByText('1 HEALTHY')).toBeInTheDocument()
    unmount()
    const second = render(
      <HomeAccountNav
        view="project"
        team={null}
        accounts={{ healthy: 1, attention: 2 }}
        onShow={vi.fn()}
      />
    )
    expect(screen.getByText('2 NEED ATTENTION')).toBeInTheDocument()
    second.unmount()
    render(
      <HomeAccountNav
        view="project"
        team={null}
        accounts={{ healthy: 0, attention: 0 }}
        onShow={vi.fn()}
      />
    )
    expect(screen.getByText('NONE LINKED')).toBeInTheDocument()
  })

  it('asks for the chosen view', async () => {
    const onShow = vi.fn()
    render(<HomeAccountNav view="project" team={null} accounts={null} onShow={onShow} />)
    await userEvent.click(screen.getByRole('button', { name: /^connected accounts/i }))
    expect(onShow).toHaveBeenCalledWith('accounts')
    await userEvent.click(screen.getByRole('button', { name: /^team & invites/i }))
    expect(onShow).toHaveBeenCalledWith('members')
  })
})
