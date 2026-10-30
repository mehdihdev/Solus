import { describe, it, expect, beforeEach, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import * as resources from '../../lib/api/resources'
import { TeleopBar } from './TeleopBar'
import { FOLLOWER, LEADER, previewFixture, teleopFixture } from './teleopFixtures'

vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources')>()),
  previewTeleop: vi.fn(),
  startTeleop: vi.fn(),
  stopTeleop: vi.fn()
}))

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(resources.previewTeleop).mockResolvedValue(previewFixture())
  vi.mocked(resources.stopTeleop).mockResolvedValue(null)
})

// Robots are passed in panel (name) order: follower first.
const ROBOTS = [FOLLOWER, LEADER]

describe('TeleopBar', () => {
  it('renders nothing with fewer than two robots', () => {
    const { container } = render(
      <TeleopBar projectId="p1" robots={[LEADER]} teleop={null} onChanged={vi.fn()} />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('defaults leader and follower by name, not by order', () => {
    render(<TeleopBar projectId="p1" robots={ROBOTS} teleop={null} onChanged={vi.fn()} />)
    expect((screen.getByLabelText('Leader') as HTMLSelectElement).value).toBe('s1')
    expect((screen.getByLabelText('Follower') as HTMLSelectElement).value).toBe('s2')
  })

  it('blocks pairing a robot with itself', () => {
    render(<TeleopBar projectId="p1" robots={ROBOTS} teleop={null} onChanged={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Follower'), { target: { value: 's1' } })
    expect(screen.getByRole('button', { name: 'Teleoperate…' })).toBeDisabled()
  })

  it('opens the confirmation dialog for the selected pair', async () => {
    render(<TeleopBar projectId="p1" robots={ROBOTS} teleop={null} onChanged={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Teleoperate…' }))
    expect(await screen.findByRole('dialog', { name: 'Teleoperate' })).toBeInTheDocument()
    await waitFor(() =>
      expect(resources.previewTeleop).toHaveBeenCalledWith('p1', {
        leader_session_id: 's1',
        follower_session_id: 's2'
      })
    )
  })

  it('keeps Stop visible while running even if a robot session drops from the list', () => {
    render(
      <TeleopBar projectId="p1" robots={[LEADER]} teleop={teleopFixture()} onChanged={vi.fn()} />
    )
    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument()
  })

  it('shows the running state with Stop', async () => {
    const onChanged = vi.fn()
    render(
      <TeleopBar projectId="p1" robots={ROBOTS} teleop={teleopFixture()} onChanged={onChanged} />
    )
    expect(
      screen.getByText('Teleoperating lerobot leader → lerobot follower · 30 Hz')
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Teleoperate…' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(resources.stopTeleop).toHaveBeenCalledWith('p1'))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('reads "holding pose" after a user stop', () => {
    render(
      <TeleopBar
        projectId="p1"
        robots={ROBOTS}
        teleop={teleopFixture({ state: 'stopped', stop_reason: 'user' })}
        onChanged={vi.fn()}
      />
    )
    expect(screen.getByRole('status')).toHaveTextContent('Stopped — follower holding pose')
    expect(screen.getByRole('status')).not.toHaveTextContent(/lost/)
    expect(screen.getByRole('button', { name: 'Teleoperate…' })).toBeInTheDocument()
  })

  it('shows the reason when the stop was not the user', () => {
    render(
      <TeleopBar
        projectId="p1"
        robots={ROBOTS}
        teleop={teleopFixture({ state: 'stopped', stop_reason: 'leader_lost' })}
        onChanged={vi.fn()}
      />
    )
    expect(screen.getByRole('status')).toHaveTextContent(
      'Stopped — follower holding pose · leader connection lost'
    )
  })
})
