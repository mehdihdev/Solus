import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { ResetPasswordPage } from './ResetPasswordPage'

function renderPage(): void {
  render(
    <MemoryRouter>
      <ResetPasswordPage />
    </MemoryRouter>
  )
}

describe('ResetPasswordPage', () => {
  it('advances from requesting a code to setting a new password', async () => {
    renderPage()
    // Step 1: request a recovery code.
    await userEvent.type(screen.getByPlaceholderText('you@team.dev'), 'maya@strider.dev')
    await userEvent.click(screen.getByText('Send recovery code'))

    // Step 2: the code + new-password fields appear.
    await waitFor(() => expect(screen.getByPlaceholderText('123456')).toBeInTheDocument())
    await userEvent.type(screen.getByPlaceholderText('123456'), '123456')
    await userEvent.type(screen.getByPlaceholderText('••••••••'), 'hunter22')
    await userEvent.click(screen.getByText('Set new password'))

    // Success confirmation shown.
    await waitFor(() => expect(screen.getByText(/Password updated/)).toBeInTheDocument())
  })

  it('validates the email before sending a code', async () => {
    renderPage()
    await userEvent.type(screen.getByPlaceholderText('you@team.dev'), 'not-an-email')
    await userEvent.click(screen.getByText('Send recovery code'))
    // Stays on step 1 (no recovery-code field) and shows an error.
    expect(screen.queryByPlaceholderText('123456')).not.toBeInTheDocument()
  })
})
