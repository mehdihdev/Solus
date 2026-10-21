import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { InviteModal, EMAIL_PATTERN } from './MembersPanel'
import type { InviteOutcome } from '../workspace/useHomeTeam'

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

describe('InviteModal', () => {
  inviteTokenLifecycleTests()
  inviteFailuresAndTeamTransitionTests()
})

type InviteFnType = (email: string) => Promise<InviteOutcome>

function inviteTokenLifecycleTests(): void {
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
}

function inviteFailuresAndTeamTransitionTests(): void {
  it('warns BEFORE Send that inviting from the personal team creates a counted team', () => {
    render(<InviteModal onClose={vi.fn()} onInvite={vi.fn()} isPersonal />)
    expect(screen.getByText(/creates a new collaborative team/)).toBeInTheDocument()
    expect(screen.getByText(/counts against your plan/)).toBeInTheDocument()
  })

  it('a failed clipboard write is said, and the token is not marked copied', async () => {
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn(async () => {
          throw new Error('denied')
        })
      }
    })
    render(<InviteModal onClose={vi.fn()} onInvite={vi.fn(async () => sent('join-tok-once'))} />)
    await userEvent.type(screen.getByPlaceholderText('teammate@team.dev'), 'new@example.dev')
    await userEvent.click(screen.getByText('Send invite'))
    await screen.findByTestId('invite-token')
    await userEvent.click(screen.getByRole('button', { name: 'Copy token' }))
    expect(await screen.findByText(/Copy failed/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Copied' })).toBeNull()
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
}
