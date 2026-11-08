import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AcademicPlanCard, type AcademicPlanCardProps } from './AcademicPlanCard'
import { ApiError } from '../../lib/api/envelope.types'
import type { AcademicStatus } from '../../lib/api/resources.academic'

const NONE: AcademicStatus = {
  state: 'none',
  email: null,
  pending_email: null,
  code_expires_at: null,
  expires_at: null,
  monthly_credits: 1000,
  suffixes: ['edu', 'ac.uk', 'edu.au']
}
const PENDING: AcademicStatus = {
  ...NONE,
  state: 'pending',
  pending_email: 'ada@mit.edu',
  code_expires_at: '2026-11-08T00:15:00Z'
}
const ACTIVE: AcademicStatus = {
  ...NONE,
  state: 'active',
  email: 'ada@mit.edu',
  expires_at: '2027-11-08T00:00:00Z'
}

const onSend = vi.fn<(email: string) => Promise<AcademicStatus>>()
const onVerify = vi.fn<(code: string) => Promise<AcademicStatus>>()
const onVerified = vi.fn()

function setup(academic: AcademicStatus | null, extra: Partial<AcademicPlanCardProps> = {}): void {
  render(
    <AcademicPlanCard
      academic={academic}
      eligible
      onSend={onSend}
      onVerify={onVerify}
      onVerified={onVerified}
      {...extra}
    />
  )
}

const step = (): HTMLElement => screen.getByRole('group', { name: 'Academic verification' })

beforeEach(() => {
  vi.clearAllMocks()
  onSend.mockResolvedValue(PENDING)
  onVerify.mockResolvedValue(ACTIVE)
})

describe('AcademicPlanCard', () => {
  it('is its own full-width card with the free terms from the server', () => {
    setup(NONE)
    const card = screen.getByRole('group', { name: 'Academic' })
    expect(within(card).getByText('FREE')).toBeInTheDocument()
    expect(
      within(card).getByText('Free for students, teachers and researchers.')
    ).toBeInTheDocument()
    expect(within(card).getByText(/1,000 credits every month/)).toBeInTheDocument()
    expect(within(card).getByText(/\.edu, \.ac\.uk, \.edu\.au/)).toBeInTheDocument()
  })

  it('sends the code and moves to the code step with focus on the code field', async () => {
    setup(NONE)
    await userEvent.type(within(step()).getByLabelText('Academic email'), 'ada@mit.edu')
    await userEvent.click(screen.getByRole('button', { name: 'Send code' }))
    expect(onSend).toHaveBeenCalledWith('ada@mit.edu')
    expect(
      screen.getByText('We sent a 6-digit code to ada@mit.edu. It expires in 15 minutes.')
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Verification code')).toHaveFocus()
    expect(screen.getByRole('button', { name: /Resend code/ })).toBeDisabled()
  })

  it('does not send an empty address', async () => {
    setup(NONE)
    expect(screen.getByRole('button', { name: 'Send code' })).toBeDisabled()
  })

  it.each([
    [
      'not_academic_email',
      422,
      "That address isn't on our list of academic domains. Use your school email."
    ],
    ['rate_limited', 429, 'Too many codes requested. Try again in a minute.'],
    ['email_unconfigured', 503, "We can't send verification emails right now. Try again later."],
    [
      'stripe_subscription_active',
      409,
      'To switch to Academic, cancel your paid plan in Manage billing first. You keep it until the period ends.'
    ]
  ])('shows the %s error inline', async (code, status, text) => {
    onSend.mockRejectedValue(new ApiError(status, code, 'server text'))
    setup(NONE)
    await userEvent.type(screen.getByLabelText('Academic email'), 'ada@mit.edu')
    await userEvent.click(screen.getByRole('button', { name: 'Send code' }))
    expect(screen.getByRole('alert')).toHaveTextContent(text)
    expect(screen.getByLabelText('Academic email')).toBeInTheDocument()
  })

  it('opens on the code step when a code is already pending', () => {
    setup(PENDING)
    expect(screen.getByLabelText('Verification code')).toBeInTheDocument()
  })

  it('verifies, tells the user, and asks the page to refresh', async () => {
    setup(PENDING)
    await userEvent.type(screen.getByLabelText('Verification code'), '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    expect(onVerify).toHaveBeenCalledWith('123456')
    expect(onVerified).toHaveBeenCalledTimes(1)
    expect(
      screen.getByText("You're on the Academic plan — 1,000 credits are in your account.")
    ).toBeInTheDocument()
  })

  it('keeps only digits and needs all six before Verify', async () => {
    setup(PENDING)
    const input = screen.getByLabelText('Verification code')
    await userEvent.type(input, '12a3 45')
    expect(input).toHaveValue('12345')
    expect(screen.getByRole('button', { name: 'Verify' })).toBeDisabled()
  })

  it('reports tries left on a wrong code', async () => {
    onVerify.mockRejectedValue(new ApiError(400, 'invalid_code', 'x', [{ attempts_left: 3 }]))
    setup(PENDING)
    await userEvent.type(screen.getByLabelText('Verification code'), '000000')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    expect(screen.getByRole('alert')).toHaveTextContent("That code didn't match — 3 tries left.")
  })

  it.each([
    ['code_expired', 410],
    ['too_many_attempts', 429],
    ['no_pending_code', 409]
  ])('asks for a new code on %s', async (code, status) => {
    onVerify.mockRejectedValue(new ApiError(status, code, 'x'))
    setup(PENDING)
    await userEvent.type(screen.getByLabelText('Verification code'), '000000')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    expect(screen.getByRole('alert')).toHaveTextContent(
      "That code can't be used anymore. Send a new one."
    )
  })

  it('says when the address is already used by another account', async () => {
    onVerify.mockRejectedValue(new ApiError(409, 'academic_email_in_use', 'x'))
    setup(PENDING)
    await userEvent.type(screen.getByLabelText('Verification code'), '000000')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    expect(screen.getByRole('alert')).toHaveTextContent(
      'That address is already verified on another Solus account.'
    )
  })

  it('goes back to the email step with "Use a different email"', async () => {
    setup(PENDING)
    await userEvent.click(screen.getByRole('button', { name: 'Use a different email' }))
    expect(screen.getByLabelText('Academic email')).toHaveValue('ada@mit.edu')
  })

  it('shows the verified address and the current-plan badge when active', () => {
    setup(ACTIVE)
    expect(
      screen.getByText('Verified ada@mit.edu · free until November 8, 2027')
    ).toBeInTheDocument()
    expect(screen.getByText('CURRENT PLAN')).toBeInTheDocument()
    expect(screen.queryByLabelText('Academic email')).not.toBeInTheDocument()
  })

  it('offers to verify again when the plan ended, prefilled', () => {
    setup({ ...ACTIVE, state: 'expired', expires_at: '2026-11-01T00:00:00Z' })
    expect(screen.getByText('Your academic plan ended November 1, 2026.')).toBeInTheDocument()
    expect(screen.getByLabelText('Academic email')).toHaveValue('ada@mit.edu')
  })

  it('explains why a paying subscriber cannot switch yet', () => {
    setup(NONE, { eligible: false })
    expect(
      screen.getByText(
        'To switch to Academic, cancel your paid plan in Manage billing first. You keep it until the period ends.'
      )
    ).toBeInTheDocument()
    expect(screen.queryByLabelText('Academic email')).not.toBeInTheDocument()
  })

  it('degrades when the status could not be loaded', () => {
    setup(null)
    expect(screen.getByText('Academic verification is unavailable right now.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Send code' })).not.toBeInTheDocument()
  })
})
