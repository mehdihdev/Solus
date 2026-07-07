import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TopBar, NotifPopover, ToastView } from './ShellChrome'
import { useShellStore } from './shellStore'
import { ALERTS } from './workspaceData.constants'

beforeEach(() => useShellStore.getState().reset())

describe('TopBar', () => {
  it('renders project, screen title, badge count, and sign out', async () => {
    const onBell = vi.fn()
    const onSignOut = vi.fn()
    render(
      <TopBar
        projectName="strider-qd12"
        screenTitle="Context Model"
        openCount={2}
        onBell={onBell}
        onSignOut={onSignOut}
      />
    )
    expect(screen.getByText('strider-qd12')).toBeInTheDocument()
    expect(screen.getByText('Context Model')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('rail-bell'))
    expect(onBell).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(onSignOut).toHaveBeenCalled()
  })
})

describe('NotifPopover', () => {
  it('lists alerts with cross-domain chips and opens one', async () => {
    const onOpen = vi.fn()
    render(<NotifPopover alerts={ALERTS} onOpen={onOpen} onClose={vi.fn()} />)
    await userEvent.click(screen.getByText('Motor driver swap breaks firmware pin map'))
    expect(onOpen).toHaveBeenCalledWith('a1')
  })
})

describe('ToastView', () => {
  it('renders the shell toast and fires the action', async () => {
    useShellStore.getState().setToast({
      title: 'SOL caught a cross-domain break',
      body: 'body',
      action: 'View alert',
      alertId: 'a1'
    })
    const onView = vi.fn()
    render(<ToastView onView={onView} />)
    await userEvent.click(screen.getByRole('button', { name: 'View alert' }))
    expect(onView).toHaveBeenCalledWith('a1')
  })

  it('renders nothing without a toast', () => {
    const { container } = render(<ToastView onView={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })
})
