// Onshape panel links (SOLUS-A7-01): approving a code, revoking a link, and
// the refusals a user must be able to act on.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PanelLinksSection } from './PanelLinksSection'
import * as resources from '../../../lib/api/resources'
import { ApiError } from '../../../lib/api/envelope.types'

vi.mock('../../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../lib/api/resources')>()
  return {
    ...actual,
    listPanelLinks: vi.fn(),
    approvePanelLink: vi.fn(),
    revokePanelLink: vi.fn()
  }
})

const LINK: resources.PanelLink = {
  id: 'b1',
  onshape_user_id: 'abc123',
  created_at: '2026-08-01T00:00:00Z',
  last_used_at: null,
  expires_at: '2026-11-01T00:00:00Z'
}

describe('PanelLinksSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(resources.listPanelLinks).mockResolvedValue([])
  })

  it('approves the code the panel is showing, normalised', async () => {
    vi.mocked(resources.approvePanelLink).mockResolvedValue({ status: 'approved' })
    render(<PanelLinksSection />)

    await userEvent.type(screen.getByLabelText('Pairing code'), ' abcd-efgh ')
    await userEvent.click(screen.getByText('Link panel'))

    await waitFor(() =>
      expect(vi.mocked(resources.approvePanelLink)).toHaveBeenCalledWith('ABCD-EFGH')
    )
  })

  it('tells the user to get a fresh code when the pairing expired', async () => {
    vi.mocked(resources.approvePanelLink).mockRejectedValue(
      new ApiError(404, 'invalid_pairing', 'nope')
    )
    render(<PanelLinksSection />)

    await userEvent.type(screen.getByLabelText('Pairing code'), 'ABCD-EFGH')
    await userEvent.click(screen.getByText('Link panel'))

    expect(await screen.findByRole('alert')).toHaveTextContent(/expired/i)
  })

  it('lists a live link and revokes it', async () => {
    vi.mocked(resources.listPanelLinks).mockResolvedValue([LINK])
    vi.mocked(resources.revokePanelLink).mockResolvedValue(undefined)
    render(<PanelLinksSection />)

    await userEvent.click(await screen.findByText('Revoke'))

    await waitFor(() => expect(vi.mocked(resources.revokePanelLink)).toHaveBeenCalledWith('b1'))
    // Refetched rather than removed locally, so the list reflects the server.
    await waitFor(() => expect(vi.mocked(resources.listPanelLinks)).toHaveBeenCalledTimes(2))
  })

  it('cannot submit an obviously incomplete code', async () => {
    render(<PanelLinksSection />)

    await userEvent.type(screen.getByLabelText('Pairing code'), 'AB')

    expect(screen.getByText('Link panel')).toBeDisabled()
  })
})
