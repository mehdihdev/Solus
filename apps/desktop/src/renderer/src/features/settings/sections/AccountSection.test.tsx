// Account danger zone (SOLUSDEV-82): permanent account deletion with the
// sole-owner 409 block surfaced instead of a silent failure.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AccountSection } from './AccountSection'
import { useAuthStore } from '../../../store/authStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import * as resources from '../../../lib/api/resources'
import { ApiError } from '../../../lib/api/envelope.types'

vi.mock('../../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../lib/api/resources')>()
  return { ...actual, deleteMe: vi.fn() }
})

describe('AccountSection — delete account', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({ status: 'authenticated' })
  })

  it('deletes the account and signs the user out', async () => {
    vi.mocked(resources.deleteMe).mockResolvedValue(undefined)
    render(<AccountSection />)
    // First click reveals the confirmation; the second (re-queried) confirms.
    await userEvent.click(screen.getByText('Delete account'))
    await userEvent.click(screen.getByText('Delete account'))
    await waitFor(() => expect(vi.mocked(resources.deleteMe)).toHaveBeenCalled())
    await waitFor(() => expect(useAuthStore.getState().status).toBe('unauthenticated'))
    expect(useWorkspaceStore.getState().linked).toBe(false)
  })

  it('surfaces the sole-owner block instead of deleting', async () => {
    vi.mocked(resources.deleteMe).mockRejectedValue(
      new ApiError(409, 'ownership_transfer_required', 'transfer first', [{ team_id: 't1' }])
    )
    render(<AccountSection />)
    await userEvent.click(screen.getByText('Delete account'))
    await userEvent.click(screen.getByText('Delete account'))
    await waitFor(() => expect(screen.getByText(/Transfer ownership/)).toBeInTheDocument())
    // Deletion was blocked — the session is untouched.
    expect(useAuthStore.getState().status).toBe('authenticated')
  })

  it('surfaces the unverified-email block instead of deleting', async () => {
    vi.mocked(resources.deleteMe).mockRejectedValue(
      new ApiError(403, 'email_not_verified', 'verify first')
    )
    render(<AccountSection />)
    await userEvent.click(screen.getByText('Delete account'))
    await userEvent.click(screen.getByText('Delete account'))
    await waitFor(() => expect(screen.getByText(/Verify your email/)).toBeInTheDocument())
    expect(useAuthStore.getState().status).toBe('authenticated')
  })

  it('cancel hides the confirmation without calling the API', async () => {
    render(<AccountSection />)
    await userEvent.click(screen.getByText('Delete account'))
    await userEvent.click(screen.getByText('Cancel'))
    expect(vi.mocked(resources.deleteMe)).not.toHaveBeenCalled()
    expect(screen.queryByText('Cancel')).not.toBeInTheDocument()
  })
})
