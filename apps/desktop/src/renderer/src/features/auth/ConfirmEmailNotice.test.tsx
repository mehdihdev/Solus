import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfirmEmailNotice } from './ConfirmEmailNotice'
import { useAuthStore } from '../../store/authStore'

describe('ConfirmEmailNotice', () => {
  beforeEach(() => {
    useAuthStore.setState({
      status: 'unauthenticated',
      user: null,
      accessToken: null,
      onboarded: false
    })
  })

  it('shows the target email and a waiting indicator', () => {
    render(
      <ConfirmEmailNotice
        email="maya@strider.dev"
        password="hunter22"
        onUseDifferentEmail={() => {}}
      />
    )
    expect(screen.getByText(/maya@strider\.dev/)).toBeInTheDocument()
    expect(screen.getByText(/Waiting for confirmation/)).toBeInTheDocument()
  })

  it('polls sign-in on an interval so confirmation auto-continues', async () => {
    const signIn = vi.fn().mockResolvedValue({})
    useAuthStore.setState({ signInWithPassword: signIn })
    vi.useFakeTimers()
    try {
      render(
        <ConfirmEmailNotice email="a@b.dev" password="hunter22" onUseDifferentEmail={() => {}} />
      )
      expect(signIn).not.toHaveBeenCalled()
      await act(async () => {
        await vi.advanceTimersByTimeAsync(4000)
      })
      expect(signIn).toHaveBeenCalledWith('a@b.dev', 'hunter22')
    } finally {
      vi.useRealTimers()
    }
  })

  it('lets the user check immediately', async () => {
    const signIn = vi.fn().mockResolvedValue({})
    useAuthStore.setState({ signInWithPassword: signIn })
    render(
      <ConfirmEmailNotice email="a@b.dev" password="pw12345678" onUseDifferentEmail={() => {}} />
    )
    await userEvent.click(screen.getByRole('button', { name: /I've confirmed/ }))
    expect(signIn).toHaveBeenCalledWith('a@b.dev', 'pw12345678')
  })

  it('resends the confirmation email and confirms it', async () => {
    const resend = vi.fn().mockResolvedValue({})
    useAuthStore.setState({ resendConfirmation: resend })
    render(
      <ConfirmEmailNotice email="a@b.dev" password="pw12345678" onUseDifferentEmail={() => {}} />
    )
    await userEvent.click(screen.getByRole('button', { name: /Resend confirmation/ }))
    expect(resend).toHaveBeenCalledWith('a@b.dev')
    expect(screen.getByText(/re-sent/)).toBeInTheDocument()
  })

  it('invokes onUseDifferentEmail from the footer link', async () => {
    const onBack = vi.fn()
    render(
      <ConfirmEmailNotice email="a@b.dev" password="pw12345678" onUseDifferentEmail={onBack} />
    )
    await userEvent.click(screen.getByText('Use a different email'))
    expect(onBack).toHaveBeenCalledOnce()
  })
})
