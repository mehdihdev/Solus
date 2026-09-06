// SOLUSDEV-246 / STORE ST3 — the detail header's pin toggle.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as ext from '../../../lib/api/resources.extensions'
import { usePinsStore } from '../pinsStore'
import { PinButton } from './PinButton'

vi.mock('../../../lib/api/resources.extensions', async (importOriginal) => ({
  ...(await importOriginal<typeof ext>()),
  pinExtension: vi.fn(),
  unpinExtension: vi.fn()
}))

const row: ext.ExtensionPinApi = {
  slug: 'bom',
  name: 'BOM',
  verified: true,
  publisher: { display_name: 'Solus' },
  version: '1.2.0',
  views: ['page'],
  page: { label: 'BOM', icon: 'icon.svg' },
  pinned_at: '2026-09-06T00:00:00Z'
}

beforeEach(() => {
  vi.clearAllMocks()
  usePinsStore.getState().reset()
})

describe('PinButton', () => {
  it('pins, then offers to unpin', async () => {
    vi.mocked(ext.pinExtension).mockResolvedValue(row)
    vi.mocked(ext.unpinExtension).mockResolvedValue(undefined)
    render(<PinButton slug="bom" />)
    await userEvent.click(screen.getByRole('button', { name: 'Pin for all projects' }))
    expect(ext.pinExtension).toHaveBeenCalledWith('bom')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Pinned for all projects' })).toHaveAttribute(
        'aria-pressed',
        'true'
      )
    )
    await userEvent.click(screen.getByRole('button', { name: 'Pinned for all projects' }))
    expect(ext.unpinExtension).toHaveBeenCalledWith('bom')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Pin for all projects' })).toBeInTheDocument()
    )
  })

  it('says so when the server refuses', async () => {
    vi.mocked(ext.pinExtension).mockRejectedValue(new Error('429'))
    render(<PinButton slug="bom" />)
    await userEvent.click(screen.getByRole('button', { name: 'Pin for all projects' }))
    expect(await screen.findByText(/Couldn't change the pin/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Pin for all projects' })).toBeInTheDocument()
  })
})
