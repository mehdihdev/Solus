// SOLUSDEV-235 — the "+ Create extension" stop-gap dialog.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CreateExtensionModal } from './CreateExtensionModal'

describe('CreateExtensionModal', () => {
  it('explains the manifest model honestly and links the docs', () => {
    render(<CreateExtensionModal onClose={vi.fn()} />)
    expect(screen.getByRole('heading', { name: 'Create an extension' })).toBeInTheDocument()
    expect(screen.getByText(/not available in this build/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /manifest documentation/i })).toHaveAttribute(
      'href',
      expect.stringMatching(/^https:\/\//)
    )
  })

  it('closes from its button', async () => {
    const onClose = vi.fn()
    render(<CreateExtensionModal onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
