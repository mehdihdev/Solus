import { describe, it, expect, beforeEach, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ApiError } from '../../lib/api/envelope.types'
import * as resources from '../../lib/api/resources'
import { RobotPanels } from './RobotPanels'
import { FOLLOWER, LEADER, teleopFixture } from './teleopFixtures'

vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources')>()),
  releaseRobot: vi.fn()
}))
vi.mock('./scene/ScenePanel', () => ({
  ScenePanel: ({ robotId }: { robotId?: string }) => <div>scene for {robotId}</div>
}))
vi.mock('./DeviceBenchView', () => ({
  DeviceBenchView: ({
    deviceIds,
    showReasoning
  }: {
    deviceIds: string[]
    showReasoning?: boolean
  }) => (
    <div>
      cards {deviceIds.join(',')} reasoning={String(showReasoning)}
    </div>
  )
}))

const release = vi.mocked(resources.releaseRobot)
const ROBOTS = [FOLLOWER, LEADER]

function renderPanels(teleop = null as ReturnType<typeof teleopFixture> | null) {
  return render(
    <RobotPanels projectId="p1" robots={ROBOTS} teleop={teleop} paused={false} onStream={vi.fn()} />
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  release.mockResolvedValue({})
})

describe('RobotPanels', () => {
  it('renders one panel per robot with only its scene and cards, without reasoning', async () => {
    renderPanels()
    const follower = screen.getByRole('region', { name: 'lerobot follower' })
    expect(await within(follower).findByText('scene for r2')).toBeInTheDocument()
    expect(within(follower).getByText(/cards usb:B\/1 reasoning=false/)).toBeInTheDocument()
    const leader = screen.getByRole('region', { name: 'lerobot leader' })
    expect(await within(leader).findByText('scene for r1')).toBeInTheDocument()
    expect(within(leader).getByText(/cards usb:A\/1/)).toBeInTheDocument()
  })

  it('asks for confirmation before releasing, then posts the release', async () => {
    renderPanels()
    const leader = screen.getByRole('region', { name: 'lerobot leader' })
    fireEvent.click(within(leader).getByRole('button', { name: 'Release…' }))
    expect(
      screen.getByText('Turn off torque on lerobot leader? It will go limp and may fall.')
    ).toBeInTheDocument()
    expect(release).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Turn off torque' }))
    await waitFor(() => expect(release).toHaveBeenCalledWith('p1', 's1'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('does not release when the dialog is cancelled', () => {
    renderPanels()
    fireEvent.click(
      within(screen.getByRole('region', { name: 'lerobot leader' })).getByRole('button', {
        name: 'Release…'
      })
    )
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(release).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows a refusal from the server', async () => {
    release.mockRejectedValue(new ApiError(409, 'not_actuated', 'no'))
    renderPanels()
    fireEvent.click(
      within(screen.getByRole('region', { name: 'lerobot leader' })).getByRole('button', {
        name: 'Release…'
      })
    )
    fireEvent.click(screen.getByRole('button', { name: 'Turn off torque' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be released/i)
  })

  it('disables Release on the follower while teleop runs, not on the leader', () => {
    renderPanels(teleopFixture())
    const follower = screen.getByRole('region', { name: 'lerobot follower' })
    const leader = screen.getByRole('region', { name: 'lerobot leader' })
    expect(within(follower).getByRole('button', { name: 'Release…' })).toBeDisabled()
    expect(within(leader).getByRole('button', { name: 'Release…' })).toBeEnabled()
  })

  it('re-enables the follower Release once teleop is stopped', () => {
    renderPanels(teleopFixture({ state: 'stopped', stop_reason: 'user' }))
    const follower = screen.getByRole('region', { name: 'lerobot follower' })
    expect(within(follower).getByRole('button', { name: 'Release…' })).toBeEnabled()
  })
})
