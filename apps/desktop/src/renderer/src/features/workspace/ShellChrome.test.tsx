import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TopBar, NotifPopover, NotificationsPopover, ToastView } from './ShellChrome'
import { useShellStore } from './shellStore'
import { ALERTS } from './workspaceData.constants'
import type { NotificationApi } from '../../lib/api/resources'

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
      title: 'Priya joined',
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
