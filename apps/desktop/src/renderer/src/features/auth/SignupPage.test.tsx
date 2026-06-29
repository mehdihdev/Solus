import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { SignupPage } from './SignupPage'
import { useAuthStore } from '../../store/authStore'

function renderSignup(): void {
  render(
    <MemoryRouter>
      <SignupPage />
    </MemoryRouter>
  )
}

describe('SignupPage', () => {
  beforeEach(() => {
    useAuthStore.setState({
      status: 'unauthenticated',
      user: null,
      accessToken: null,
      onboarded: false
    })
  })

  it('shows validation errors for bad input and does not authenticate', async () => {
    renderSignup()
    await userEvent.type(screen.getByLabelText('WORK EMAIL'), 'not-an-email')
    await userEvent.type(screen.getByLabelText('PASSWORD'), 'short')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(screen.getByText('Enter a valid email address')).toBeInTheDocument()
    expect(screen.getByText('At least 8 characters')).toBeInTheDocument()
    expect(useAuthStore.getState().status).toBe('unauthenticated')
  })

  it('authenticates on valid submit (dev bypass)', async () => {
    renderSignup()
    await userEvent.type(screen.getByLabelText('WORK EMAIL'), 'maya@strider.dev')
    await userEvent.type(screen.getByLabelText('PASSWORD'), 'hunter22')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(useAuthStore.getState().status).toBe('authenticated')
    expect(useAuthStore.getState().user?.email).toBe('maya@strider.dev')
  })

  it('offers a GitHub option', () => {
    renderSignup()
    expect(screen.getByRole('button', { name: /Continue with GitHub/ })).toBeInTheDocument()
  })

  it('shows the confirm-email screen when confirmation is required', async () => {
    useAuthStore.setState({
      signUpWithPassword: vi.fn().mockResolvedValue({ needsConfirmation: true })
    })
    renderSignup()
    await userEvent.type(screen.getByLabelText('WORK EMAIL'), 'maya@strider.dev')
    await userEvent.type(screen.getByLabelText('PASSWORD'), 'hunter22')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(screen.getByText('Confirm your email')).toBeInTheDocument()
    expect(screen.getByText(/maya@strider\.dev/)).toBeInTheDocument()
    expect(useAuthStore.getState().status).toBe('unauthenticated')
  })

  it('returns to the form via "Use a different email"', async () => {
    useAuthStore.setState({
      signUpWithPassword: vi.fn().mockResolvedValue({ needsConfirmation: true })
    })
    renderSignup()
    await userEvent.type(screen.getByLabelText('WORK EMAIL'), 'maya@strider.dev')
    await userEvent.type(screen.getByLabelText('PASSWORD'), 'hunter22')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    await userEvent.click(screen.getByText('Use a different email'))
    expect(screen.getByRole('button', { name: 'Create account' })).toBeInTheDocument()
  })
})
