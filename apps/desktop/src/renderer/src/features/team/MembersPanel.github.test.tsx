// SOLUSDEV-317: each teammate's GitHub link on the members list (everyone sees
// it), and the admin-only "Assign GitHub…" that hands off to GITHUB ORG MEMBERS.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LiveMembers, type LiveMembersProps } from './MembersPanel'
import type { TeamMemberApi } from '../../lib/api/resources'

const VERIFIED: TeamMemberApi = {
  user_id: 'u1',
  email: 'maya@example.dev',
  name: 'Maya K',
  role: 'owner',
  joined_at: '',
  github: { github_id: 1, github_login: 'maya-k', avatar_url: null, source: 'verified' }
}
const ASSIGNED: TeamMemberApi = {
  user_id: 'u2',
  email: 'noor@example.dev',
  name: 'Noor A',
  role: 'member',
  joined_at: '',
  github: { github_id: 2, github_login: '<b>noor</b>', avatar_url: null, source: 'admin' }
}
const UNLINKED: TeamMemberApi = {
  user_id: 'u3',
  email: 'sam@example.dev',
  name: 'Sam',
  role: 'member',
  joined_at: ''
}

function renderMembers(over: Partial<LiveMembersProps> = {}): void {
  render(
    <LiveMembers
      members={[VERIFIED, ASSIGNED, UNLINKED]}
      invites={[]}
      myRole="member"
      canManage={false}
      onChangeRole={vi.fn()}
      onRemove={vi.fn()}
      onRevoke={vi.fn()}
      {...over}
    />
  )
}

const badge = (login: string): HTMLElement => screen.getByTestId(`member-github-${login}`)

describe('LiveMembers — GitHub link', () => {
  it('shows the GitHub mark, @login and a verified / assigned tag to everyone', () => {
    renderMembers()
    expect(within(badge('maya-k')).getByText('@maya-k')).toBeInTheDocument()
    expect(within(badge('maya-k')).getByText('verified')).toBeInTheDocument()
    expect(within(badge('<b>noor</b>')).getByText('assigned')).toBeInTheDocument()
    expect(badge('maya-k').querySelector('img')).toHaveClass('logo-mono')
  })

  it('renders a hostile login as text', () => {
    renderMembers()
    expect(screen.getByText('@<b>noor</b>')).toBeInTheDocument()
  })

  it('offers no "Assign GitHub…" to non-admins', () => {
    renderMembers({ onAssignGithub: vi.fn() })
    expect(screen.queryByRole('button', { name: /assign github/i })).toBeNull()
  })

  it('admins get "Assign GitHub…" only on unlinked members, and it hands off', async () => {
    const onAssignGithub = vi.fn()
    renderMembers({ canManage: true, myRole: 'owner', onAssignGithub })
    const buttons = screen.getAllByRole('button', { name: /assign github/i })
    expect(buttons).toHaveLength(1)
    expect(buttons[0]).toHaveAccessibleName('Assign GitHub to sam@example.dev')
    await userEvent.click(buttons[0])
    expect(onAssignGithub).toHaveBeenCalledWith(UNLINKED)
  })

  it('has no affordance when the org members section is not on screen', () => {
    renderMembers({ canManage: true, myRole: 'owner' })
    expect(screen.queryByRole('button', { name: /assign github/i })).toBeNull()
  })
})
