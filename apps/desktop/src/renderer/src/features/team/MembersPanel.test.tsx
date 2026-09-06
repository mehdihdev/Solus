import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LiveMembers, InviteModal, EMAIL_PATTERN } from './MembersPanel'
import type { InviteApi, TeamMemberApi } from '../../lib/api/resources'
import type { InviteOutcome } from '../workspace/useHomeTeam'

const MEMBERS: TeamMemberApi[] = [
  { user_id: 'u1', email: 'maya@example.dev', name: 'Maya K', role: 'owner', joined_at: '' },
  { user_id: 'u2', email: 'noor@example.dev', name: 'Noor A', role: 'member', joined_at: '' }
]
const INVITES: InviteApi[] = [
  {
    id: 'i1',
    team_id: 't1',
    email: 'new@example.dev',
    role: 'member',
    status: 'pending',
    created_at: '',
    expires_at: ''
  }
]

const sent = (token: string | null, movedToTeamId: string | null = null): InviteOutcome => ({
  ok: true,
  token,
  movedToTeamId
})

describe('EMAIL_PATTERN', () => {
  it('accepts a valid email and rejects malformed input', () => {
    expect(EMAIL_PATTERN.test('a@b.dev')).toBe(true)
    expect(EMAIL_PATTERN.test('not-an-email')).toBe(false)
  })
})

describe('LiveMembers', () => {
  it('renders the roster with each role', () => {
    render(
      <LiveMembers
        members={MEMBERS}
        invites={[]}
        myRole="owner"
        canManage={false}
        onChangeRole={vi.fn()}
        onRemove={vi.fn()}
        onRevoke={vi.fn()}
      />
    )
    expect(screen.getByText('Maya K')).toBeInTheDocument()
    expect(screen.getByText('noor@example.dev')).toBeInTheDocument()
    expect(screen.getByText('● OWNER')).toBeInTheDocument()
    expect(screen.getByText('● MEMBER')).toBeInTheDocument()
  })

  it('shows role/remove controls to a manager but never for the owner row', () => {
    render(
      <LiveMembers
        members={MEMBERS}
        invites={[]}
        myRole="owner"
        canManage
        onChangeRole={vi.fn()}
        onRemove={vi.fn()}
        onRevoke={vi.fn()}
      />
    )
    // Owner row stays static; the member gets a role selector + remove button.
    expect(screen.getByLabelText('Role for noor@example.dev')).toBeInTheDocument()
    expect(screen.queryByLabelText('Role for maya@example.dev')).not.toBeInTheDocument()
  })

  it('changes a role and removes a member through the callbacks', async () => {
    const onChangeRole = vi.fn()
    const onRemove = vi.fn()
    render(
      <LiveMembers
        members={MEMBERS}
        invites={[]}
        myRole="owner"
        canManage
        onChangeRole={onChangeRole}
        onRemove={onRemove}
        onRevoke={vi.fn()}
      />
    )
    await userEvent.selectOptions(screen.getByLabelText('Role for noor@example.dev'), 'admin')
    expect(onChangeRole).toHaveBeenCalledWith('u2', 'admin')
    await userEvent.click(screen.getByLabelText('Remove noor@example.dev'))
    expect(onRemove).toHaveBeenCalledWith('u2')
  })

  it('renders pending invites and revokes them when managing', async () => {
    const onRevoke = vi.fn()
    render(
      <LiveMembers
        members={MEMBERS}
        invites={INVITES}
        myRole="owner"
        canManage
        onChangeRole={vi.fn()}
        onRemove={vi.fn()}
        onRevoke={onRevoke}
      />
    )
    expect(screen.getByText('new@example.dev')).toBeInTheDocument()
    expect(screen.getByText(/INVITE PENDING/)).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('Revoke invite for new@example.dev'))
    expect(onRevoke).toHaveBeenCalledWith('i1')
  })
})

describe('InviteModal', () => {
  it('rejects an invalid email inline', async () => {
    const onInvite = vi.fn(async () => sent('x'))
    render(<InviteModal onClose={vi.fn()} onInvite={onInvite} />)
    await userEvent.type(screen.getByPlaceholderText('teammate@team.dev'), 'nope')
    await userEvent.click(screen.getByText('Send invite'))
    expect(screen.getByText('Enter a valid email address.')).toBeInTheDocument()
    expect(onInvite).not.toHaveBeenCalled()
  })

  it('reveals the one-time token, copies it, and closes on Done', async () => {
    const writeText = vi.fn(async () => undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    const onClose = vi.fn()
    render(<InviteModal onClose={onClose} onInvite={vi.fn(async () => sent('join-tok-once'))} />)
    await userEvent.type(screen.getByPlaceholderText('teammate@team.dev'), 'new@example.dev')
    await userEvent.click(screen.getByText('Send invite'))
    await waitFor(() =>
      expect(screen.getByTestId('invite-token')).toHaveTextContent('join-tok-once')
    )
    await userEvent.click(screen.getByRole('button', { name: 'Copy token' }))
    expect(writeText).toHaveBeenCalledWith('join-tok-once')
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('guards Done while the token is uncopied — it takes a second click', async () => {
    const onClose = vi.fn()
    render(<InviteModal onClose={onClose} onInvite={vi.fn(async () => sent('join-tok-once'))} />)
    await userEvent.type(screen.getByPlaceholderText('teammate@team.dev'), 'new@example.dev')
    await userEvent.click(screen.getByText('Send invite'))
    await screen.findByTestId('invite-token')
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent(/won.t see this token again/)
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('says when the invite moved to a new team spun up from the personal one', async () => {
    render(<InviteModal onClose={vi.fn()} onInvite={vi.fn(async () => sent('t', 't-new'))} />)
    await userEvent.type(screen.getByPlaceholderText('teammate@team.dev'), 'new@example.dev')
    await userEvent.click(screen.getByText('Send invite'))
    expect(await screen.findByText(/Home has switched to it/)).toBeInTheDocument()
  })

  it('names each refusal; a plan limit shows the upgrade path', async () => {
    const onUpgrade = vi.fn()
    const onInvite = vi.fn<InviteFnType>()
    render(<InviteModal onClose={vi.fn()} onInvite={onInvite} onUpgrade={onUpgrade} />)
    const email = screen.getByPlaceholderText('teammate@team.dev')
    await userEvent.type(email, 'new@example.dev')
    onInvite.mockResolvedValueOnce({ ok: false, reason: 'already_member' })
    await userEvent.click(screen.getByText('Send invite'))
    expect(await screen.findByText(/already on this team/)).toBeInTheDocument()
    onInvite.mockResolvedValueOnce({ ok: false, reason: 'invite_pending' })
    await userEvent.click(screen.getByText('Send invite'))
    expect(await screen.findByText(/already pending/)).toBeInTheDocument()
    onInvite.mockResolvedValueOnce({
      ok: false,
      reason: 'plan_limit',
      limit: { limit: 'max_teams', current: 2, max: 2, message: 'At your team limit.' }
    })
    await userEvent.click(screen.getByText('Send invite'))
    expect(await screen.findByTestId('plan-limit')).toHaveTextContent('At your team limit.')
    await userEvent.click(screen.getByRole('button', { name: 'Upgrade' }))
    expect(onUpgrade).toHaveBeenCalled()
  })
})

type InviteFnType = (email: string) => Promise<InviteOutcome>
