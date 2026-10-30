import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { ApiError } from '../../lib/api/envelope.types'
import * as resources from '../../lib/api/resources'
import { TeleopDialog } from './TeleopDialog'
import { FOLLOWER, LEADER, previewFixture, teleopFixture } from './teleopFixtures'

vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources')>()),
  previewTeleop: vi.fn(),
  startTeleop: vi.fn()
}))
const preview = vi.mocked(resources.previewTeleop)
const start = vi.mocked(resources.startTeleop)

async function flush(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
}
function open(onStarted = vi.fn(), onClose = vi.fn()): { onStarted: typeof onStarted } {
  render(
    <TeleopDialog
      projectId="p1"
      leader={LEADER}
      follower={FOLLOWER}
      onStarted={onStarted}
      onClose={onClose}
    />
  )
  return { onStarted }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
})
afterEach(() => vi.useRealTimers())

describe('TeleopDialog', () => {
  it('names both robots and renders the pairing table', async () => {
    preview.mockResolvedValue(previewFixture())
    open()
    await flush()
    expect(preview).toHaveBeenCalledWith('p1', {
      leader_session_id: 's1',
      follower_session_id: 's2'
    })
    expect(screen.getByRole('dialog', { name: /teleoperate/i })).toHaveTextContent('lerobot leader')
    expect(screen.getByText('shoulder_pan')).toBeInTheDocument()
    expect(screen.getByText('10.0 deg')).toBeInTheDocument()
    expect(screen.getByText('12.5 deg')).toBeInTheDocument()
    expect(screen.getByText('2.5')).toBeInTheDocument()
    expect(screen.getByLabelText('within tolerance')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start teleoperation' })).toBeEnabled()
  })

  it('refreshes the preview about twice a second', async () => {
    preview.mockResolvedValue(previewFixture())
    open()
    await flush()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100)
    })
    expect(preview.mock.calls.length).toBeGreaterThanOrEqual(3)
  })

  it('lists blockers in plain words and keeps Start disabled', async () => {
    preview.mockResolvedValue(
      previewFixture({
        ready: false,
        blockers: [{ code: 'uncalibrated_joint', message: 'Joint 3 is not calibrated.' }],
        pairs: []
      })
    )
    open()
    await flush()
    expect(screen.getByText('Joint 3 is not calibrated.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start teleoperation' })).toBeDisabled()
  })

  it('asks to move the leader closer when a joint is out of tolerance', async () => {
    const base = previewFixture()
    preview.mockResolvedValue(
      previewFixture({
        ready: false,
        pairs: [{ ...base.pairs[0], delta: 40, within_tolerance: false }]
      })
    )
    open()
    await flush()
    expect(screen.getByText(/move the leader closer to the follower's pose/i)).toBeInTheDocument()
    expect(screen.getByLabelText('outside tolerance')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start teleoperation' })).toBeDisabled()
  })

  it('posts the latest preview_id with confirm and reports the started teleop', async () => {
    preview.mockResolvedValue(previewFixture({ preview_id: 'latest' }))
    start.mockResolvedValue(teleopFixture())
    const { onStarted } = open()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start teleoperation' }))
    await flush()
    expect(start).toHaveBeenCalledWith('p1', 'latest')
    expect(onStarted).toHaveBeenCalledWith(expect.objectContaining({ id: 't1' }))
  })

  it('shows the fresh table from a 409 teleop_not_ready', async () => {
    preview.mockResolvedValue(previewFixture())
    const base = previewFixture()
    const fresh = previewFixture({
      ready: false,
      pairs: [{ ...base.pairs[0], leader_signal: 'fresh_joint', within_tolerance: false }]
    })
    start.mockRejectedValue(new ApiError(409, 'teleop_not_ready', 'not ready', [fresh]))
    const { onStarted } = open()
    await flush()
    // The server's next preview agrees with the fresh table it just returned.
    preview.mockResolvedValue(fresh)
    fireEvent.click(screen.getByRole('button', { name: 'Start teleoperation' }))
    await flush()
    expect(screen.getByText('fresh_joint')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(/not ready/i)
    expect(onStarted).not.toHaveBeenCalled()
  })

  it('re-previews after a 410 preview_expired', async () => {
    preview.mockResolvedValue(previewFixture())
    start.mockRejectedValue(new ApiError(410, 'preview_expired', 'gone'))
    open()
    await flush()
    const before = preview.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: 'Start teleoperation' }))
    await flush()
    expect(preview.mock.calls.length).toBeGreaterThan(before)
    expect(screen.getByRole('alert')).toHaveTextContent(/expired/i)
  })

  it('shows an error when the preview itself fails', async () => {
    preview.mockRejectedValue(new ApiError(404, 'session_not_found', 'no session'))
    open()
    await flush()
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start teleoperation' })).toBeDisabled()
  })
})
