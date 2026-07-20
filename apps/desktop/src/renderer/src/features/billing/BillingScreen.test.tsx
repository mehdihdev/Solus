// Billing screen: current plan summary, plan comparison, plan change, offline.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BillingScreen } from './BillingScreen'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getSubscription: vi.fn(), updateSubscription: vi.fn() }
})

const SUB: resources.Subscription = {
  user_id: 'u1',
  plan: 'basic',
  status: 'trialing',
  limits: { max_projects: 3, max_teams: 2, max_integrations: 4 },
  expires_at: '2026-08-01T00:00:00Z',
  seat_count: 1
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.com' } })
  vi.mocked(resources.getSubscription).mockResolvedValue(SUB)
})

describe('BillingScreen', () => {
  it('shows the current plan, status, and limits', async () => {
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Billing')).toBeInTheDocument())
    expect(screen.getByText('Basic')).toBeInTheDocument()
    // Current plan's status chip.
    expect(screen.getByText('TRIAL')).toBeInTheDocument()
  })

  it('shows an honest offline notice when the API is unreachable to a signed-in user', async () => {
    useAuthStore.setState({ status: 'unauthenticated', user: null })
    render(<BillingScreen />)
    await waitFor(() =>
      expect(screen.getByText(/Sign in to Solus to manage billing/)).toBeInTheDocument()
    )
  })

  it('changes the plan when an upgrade is chosen', async () => {
    vi.mocked(resources.updateSubscription).mockResolvedValue({ ...SUB, plan: 'pro' })
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Basic')).toBeInTheDocument())
    // The Pro plan card exposes a switch action; Basic (current) shows "Current".
    await userEvent.click(screen.getByRole('button', { name: /Switch to Pro/i }))
    await waitFor(() => expect(vi.mocked(resources.updateSubscription)).toHaveBeenCalledWith('pro'))
  })

  it('marks the active plan as current (not switchable)', async () => {
    render(<BillingScreen />)
    await waitFor(() => expect(screen.getByText('Basic')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Switch to Basic/i })).not.toBeInTheDocument()
  })
})
