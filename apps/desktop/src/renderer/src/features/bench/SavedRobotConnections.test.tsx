import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { listEntities, type Entity } from '../../lib/api/resources'
import { SavedRobotConnections } from './SavedRobotConnections'

vi.mock('../../lib/api/resources', () => ({ listEntities: vi.fn() }))
const robot: Entity = {
  id: 'r1',
  project_id: 'p1',
  type: 'physical_robot',
  origin: 'manual',
  source_id: null,
  domain: 'mechanical',
  name: 'Follower',
  source_key: 'r1'
}
beforeEach(() => {
  vi.mocked(listEntities).mockReset()
})

it('opens the accepted robot config and prevents duplicate starts', async () => {
  vi.mocked(listEntities).mockResolvedValue([robot])
  let finish!: (value: string | null) => void
  const connect = vi.fn(
    () =>
      new Promise<string | null>((resolve) => {
        finish = resolve
      })
  )
  render(<SavedRobotConnections projectId="p1" onConnect={connect} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Connect saved Follower' }))
  expect(connect).toHaveBeenCalledWith({
    mode: 'real',
    config: { provider: 'robot', robot_entity_id: 'r1' }
  })
  expect(screen.getByRole('button', { name: 'Connect saved Follower' })).toBeDisabled()
  await act(async () => finish('Saved calibration needs review'))
  expect(screen.getByRole('alert')).toHaveTextContent('Saved calibration needs review')
})

it('bounds search and refuses imported or foreign entries', async () => {
  vi.mocked(listEntities).mockResolvedValue([
    robot,
    { ...robot, id: 'foreign', project_id: 'p2' },
    { ...robot, id: 'imported', origin: 'connector' }
  ])
  render(<SavedRobotConnections projectId="p1" onConnect={vi.fn()} />)
  expect(await screen.findAllByRole('button', { name: /Connect saved/ })).toHaveLength(1)
  fireEvent.change(screen.getByRole('textbox', { name: 'Find saved robot' }), {
    target: { value: 'Leader' }
  })
  await waitFor(() =>
    expect(listEntities).toHaveBeenLastCalledWith('p1', {
      type: 'physical_robot',
      q: 'Leader',
      limit: 24
    })
  )
})

it('discards an old project response', async () => {
  let finish!: (value: Entity[]) => void
  vi.mocked(listEntities)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
    .mockResolvedValue([])
  const view = render(<SavedRobotConnections projectId="p1" onConnect={vi.fn()} />)
  view.rerender(<SavedRobotConnections projectId="p2" onConnect={vi.fn()} />)
  await act(async () => finish([robot]))
  expect(screen.queryByRole('button', { name: 'Connect saved Follower' })).toBeNull()
})
