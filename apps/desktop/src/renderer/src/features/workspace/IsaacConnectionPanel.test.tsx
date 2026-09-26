import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import {
  getIsaacConnectionStatus,
  type IsaacConnectionStatus
} from '../../lib/api/resources.isaacConnection'
import { IsaacConnectionPanel } from './IsaacConnectionPanel'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'

vi.mock('../../lib/api/resources.isaacConnection', () => ({ getIsaacConnectionStatus: vi.fn() }))
const status: IsaacConnectionStatus = {
  bridge: 'connected',
  installation: 'installed',
  owned_session: 'not_running',
  streaming: 'none',
  reason: null
}
beforeEach(() => {
  vi.clearAllMocks()
  useAuthStore.setState({ user: { email: 'a@example.test' } })
  useWorkspaceStore.setState({ project: { id: 'project', name: 'A' } })
  vi.mocked(getIsaacConnectionStatus).mockResolvedValue(status)
})

it.each(['account', 'project'])(
  'discards a pending observation across a batched %s round trip',
  async (boundary) => {
    vi.useFakeTimers()
    let finish!: (value: IsaacConnectionStatus) => void
    vi.mocked(getIsaacConnectionStatus).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
    render(<IsaacConnectionPanel projectId="project" />)
    fireEvent.click(screen.getByRole('button', { name: 'Connect status monitoring' }))
    act(() => {
      if (boundary === 'account') {
        useAuthStore.setState({ user: { email: 'b@example.test' } })
        useAuthStore.setState({ user: { email: 'a@example.test' } })
      } else {
        useWorkspaceStore.setState({ project: { id: 'other', name: 'B' } })
        useWorkspaceStore.setState({ project: { id: 'project', name: 'A' } })
      }
    })
    await act(async () => {
      finish(status)
      await vi.advanceTimersByTimeAsync(20000)
    })
    expect(screen.queryByText('Installed')).toBeNull()
    expect(screen.getByRole('button', { name: 'Connect status monitoring' })).toBeInTheDocument()
    expect(getIsaacConnectionStatus).toHaveBeenCalledTimes(1)
  }
)

it('clears the previous account snapshot and stops polling on identity change', async () => {
  vi.useFakeTimers()
  render(<IsaacConnectionPanel projectId="project" />)
  fireEvent.click(screen.getByRole('button', { name: 'Connect status monitoring' }))
  await act(() => vi.advanceTimersByTimeAsync(0))
  expect(screen.getByText('Installed')).toBeInTheDocument()
  act(() => useAuthStore.setState({ user: { email: 'b@example.test' } }))
  expect(screen.queryByText('Installed')).toBeNull()
  await act(() => vi.advanceTimersByTimeAsync(20000))
  expect(getIsaacConnectionStatus).toHaveBeenCalledTimes(1)
})
afterEach(() => vi.useRealTimers())

it('does nothing until Connect and reports no streaming or model offer', async () => {
  render(<IsaacConnectionPanel projectId="project" />)
  expect(getIsaacConnectionStatus).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Connect status monitoring' }))
  expect(await screen.findByText('Installed')).toBeInTheDocument()
  expect(screen.getByText('Owned session not running')).toBeInTheDocument()
  expect(screen.getByText(/Streaming: none/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /start|import|model/i })).toBeNull()
})

it('ignores a pending old-project response and does not auto-connect the next project', async () => {
  let resolve: ((value: IsaacConnectionStatus) => void) | undefined
  vi.mocked(getIsaacConnectionStatus).mockReturnValue(
    new Promise((done) => {
      resolve = done
    })
  )
  const view = render(<IsaacConnectionPanel projectId="first" />)
  fireEvent.click(screen.getByRole('button', { name: 'Connect status monitoring' }))
  view.rerender(<IsaacConnectionPanel projectId="second" />)
  await act(async () => resolve?.(status))
  expect(screen.queryByText('Installed')).toBeNull()
  expect(screen.getByRole('button', { name: 'Connect status monitoring' })).toBeInTheDocument()
  expect(getIsaacConnectionStatus).toHaveBeenCalledTimes(1)
})

it('Disconnect aborts monitoring without calling a simulator stop action', async () => {
  render(<IsaacConnectionPanel projectId="project" />)
  fireEvent.click(screen.getByRole('button', { name: 'Connect status monitoring' }))
  await screen.findByText('Installed')
  const signal = vi.mocked(getIsaacConnectionStatus).mock.calls[0]?.[1]
  fireEvent.click(screen.getByRole('button', { name: 'Disconnect status monitoring' }))
  expect(signal?.aborted).toBe(true)
  expect(screen.queryByText('Installed')).toBeNull()
})

it('keeps unsuccessful observations unknown without showing raw errors', async () => {
  vi.mocked(getIsaacConnectionStatus).mockRejectedValue(new Error('/private/runtime/log'))
  render(<IsaacConnectionPanel projectId="project" />)
  fireEvent.click(screen.getByRole('button', { name: 'Connect status monitoring' }))
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Status unavailable'))
  expect(screen.queryByText(/private/)).toBeNull()
})

it('polls after ten seconds with at most one read in flight', async () => {
  vi.useFakeTimers()
  render(<IsaacConnectionPanel projectId="project" />)
  fireEvent.click(screen.getByRole('button', { name: 'Connect status monitoring' }))
  await act(async () => {
    await Promise.resolve()
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(9999)
  })
  expect(getIsaacConnectionStatus).toHaveBeenCalledTimes(1)
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1)
  })
  expect(getIsaacConnectionStatus).toHaveBeenCalledTimes(2)
})
