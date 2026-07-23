// Shell chrome (SOLUSDEV-152): topbar, live notifications popover, the honest
// offline popover (no demo alerts), and the toast.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TopBar, OfflineNotifPopover, NotificationsPopover, ToastView } from './ShellChrome'
import { useShellStore } from './shellStore'
import type { NotificationApi } from '../../lib/api/resources'

beforeEach(() => useShellStore.getState().reset())

describe('TopBar', () => {
  it('renders project, screen title, badge count, and sign out', async () => {
    const onBell = vi.fn()
    const onSignOut = vi.fn()
    render(
      <TopBar
        projectSlot={<span>Rover MK2</span>}
        screenTitle="Context Model"
        openCount={2}
        onHome={vi.fn()}
        onBell={onBell}
        onSignOut={onSignOut}
      />
    )
    expect(screen.getByText('Rover MK2')).toBeInTheDocument()
    expect(screen.getByText('Context Model')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('rail-bell'))
    expect(onBell).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(onSignOut).toHaveBeenCalled()
  })

  it('offers a Home breadcrumb back to the workspace home (SOLUSDEV-164)', async () => {
    const onHome = vi.fn()
    render(
      <TopBar
        projectSlot={<span>Rover MK2</span>}
        screenTitle="Sources"
        openCount={0}
        onHome={onHome}
        onBell={vi.fn()}
        onSignOut={vi.fn()}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: 'Home' }))
    expect(onHome).toHaveBeenCalled()
  })

  it('hides the badge at zero unread', () => {
    render(
      <TopBar
        projectSlot={<span>Rover MK2</span>}
        screenTitle="Home"
        openCount={0}
        onHome={vi.fn()}
        onBell={vi.fn()}
        onSignOut={vi.fn()}
      />
    )
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })
})

describe('OfflineNotifPopover', () => {
  it('shows an honest sign-in message instead of demo alerts', async () => {
    const onClose = vi.fn()
    render(<OfflineNotifPopover onClose={onClose} />)
    expect(screen.getByText('NOTIFICATIONS')).toBeInTheDocument()
    expect(screen.getByText(/Sign in to Solus to see notifications/)).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('Close notifications'))
    expect(onClose).toHaveBeenCalled()
  })
})

describe('NotificationsPopover', () => {
  const NOTIFS: NotificationApi[] = [
    {
      id: 'n1',
      type: 'team.invite',
      title: 'You were invited',
      body: null,
      payload: {},
      read_at: null,
      created_at: '2026-07-06T00:00:00Z'
    },
    {
      id: 'n2',
      type: 'invite.accepted',
      title: 'Noor joined',
      body: null,
      payload: {},
      read_at: '2026-07-05T00:00:00Z',
      created_at: '2026-07-05T00:00:00Z'
    }
  ]

  it('marks one read on row click and marks all read from the header', async () => {
    const onRead = vi.fn()
    const onReadAll = vi.fn()
    render(
      <NotificationsPopover
        items={NOTIFS}
        onRead={onRead}
        onReadAll={onReadAll}
        onClose={vi.fn()}
      />
    )
    await userEvent.click(screen.getByText('You were invited'))
    expect(onRead).toHaveBeenCalledWith('n1')
    await userEvent.click(screen.getByRole('button', { name: 'Mark all read' }))
    expect(onReadAll).toHaveBeenCalled()
  })

  it('hides mark-all-read when everything is already read', () => {
    render(
      <NotificationsPopover
        items={[NOTIFS[1]]}
        onRead={vi.fn()}
        onReadAll={vi.fn()}
        onClose={vi.fn()}
      />
    )
    expect(screen.queryByRole('button', { name: 'Mark all read' })).not.toBeInTheDocument()
  })
})

describe('ToastView', () => {
  it('renders the shell toast and fires the action', async () => {
    useShellStore.getState().setToast({
      title: 'Action needed',
      body: 'body',
      action: 'View',
      alertId: 'n1'
    })
    const onView = vi.fn()
    render(<ToastView onView={onView} />)
    await userEvent.click(screen.getByRole('button', { name: 'View' }))
    expect(onView).toHaveBeenCalledWith('n1')
  })

  it('renders nothing without a toast', () => {
    const { container } = render(<ToastView onView={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })
})
