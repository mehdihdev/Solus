import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import type { Entity } from '../../../lib/api/resources'
import { readHardwareTopology } from '../../../lib/api/hardwareTopology'
import { RobotTopologyGraph } from './RobotTopologyGraph'

vi.mock('../../../lib/api/hardwareTopology', () => ({ readHardwareTopology: vi.fn() }))
const entity = (id: string, type = 'part'): Entity => ({
  id,
  name: id,
  type,
  source_key: id,
  domain: 'mechanical'
})
const entities = [
  entity('robot', 'physical_robot'),
  entity('category', 'robot_category'),
  ...['host', 'bus', 'controller', 'downstream', 'motor', 'sensor'].map((id) => entity(id))
]
const topology = {
  robot_id: 'robot',
  roots: ['host'],
  nodes: ['host', 'bus', 'controller', 'downstream', 'motor', 'sensor'].map((id) => ({
    id,
    name: id,
    role:
      id === 'host' || id === 'controller'
        ? 'brain'
        : id === 'bus' || id === 'downstream'
          ? 'bus'
          : 'part',
    brain_kind: id === 'host' ? 'host' : null,
    category: id === 'motor' ? 'actuators' : id === 'sensor' ? 'sensors' : null,
    channel: id === 'controller' ? 'usb_serial' : null,
    software: null,
    presence: null,
    evidence: []
  })),
  edges: [
    ['host', 'bus'],
    ['bus', 'controller'],
    ['controller', 'downstream'],
    ['downstream', 'motor'],
    ['bus', 'sensor']
  ].map(([source, target]) => ({
    id: `${source}-${target}`,
    source,
    target,
    protocol: null,
    address: null
  }))
}
const props = {
  projectId: 'p1',
  entities,
  relations: [],
  positions: {},
  focusedId: null,
  onSelect: vi.fn(),
  onMove: vi.fn()
}
const enter = (id: string): boolean =>
  fireEvent.doubleClick(
    within(screen.getByTestId(`graph-node-${id}`)).getByRole('button', { name: `Select ${id}` })
  )
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(readHardwareTopology).mockResolvedValue(
    topology as Awaited<ReturnType<typeof readHardwareTopology>>
  )
})
it('mounts the real connection card on a USB endpoint and never on the host brain', async () => {
  render(<RobotTopologyGraph {...props} />)
  await screen.findByRole('button', { name: 'Actuators / motors' })
  enter('robot')
  expect(screen.queryByRole('button', { name: 'Connect this computer' })).toBeNull()
  enter('host')
  enter('bus')
  expect(
    within(screen.getByTestId('graph-node-controller')).getByRole('button', {
      name: 'Connect this computer'
    })
  ).toBeTruthy()
})
it('renders real API topology through the existing navigator, preserving ancestors under category filtering', async () => {
  render(<RobotTopologyGraph {...props} />)
  await screen.findByRole('button', { name: 'Actuators / motors' })
  expect(readHardwareTopology).toHaveBeenCalledWith('p1', 'robot', expect.any(AbortSignal))
  fireEvent.click(screen.getByRole('button', { name: 'Actuators / motors' }))
  enter('robot')
  enter('host')
  enter('bus')
  expect(screen.queryByTestId('graph-node-sensor')).not.toBeInTheDocument()
  expect(screen.getAllByTestId('graph-node-controller')).toHaveLength(1)
  enter('controller')
  enter('downstream')
  expect(screen.getByTestId('graph-node-motor')).toBeInTheDocument()
  expect(screen.queryByTestId('graph-node-category')).not.toBeInTheDocument()
})
it('reports unavailable topology without concealing existing parts', async () => {
  vi.mocked(readHardwareTopology).mockRejectedValue(new Error('offline'))
  render(<RobotTopologyGraph {...props} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Topology unavailable')
  expect(screen.getByTestId('graph-node-motor')).toBeInTheDocument()
})
it('discards a late response after changing projects', async () => {
  let resolve!: (value: Awaited<ReturnType<typeof readHardwareTopology>>) => void
  vi.mocked(readHardwareTopology).mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done
      })
  )
  const view = render(<RobotTopologyGraph {...props} />)
  view.rerender(<RobotTopologyGraph {...props} projectId="p2" entities={[]} />)
  await act(async () => resolve(topology as Awaited<ReturnType<typeof readHardwareTopology>>))
  expect(screen.queryByRole('button', { name: 'Actuators / motors' })).not.toBeInTheDocument()
  expect(screen.queryByTestId('graph-node-host')).not.toBeInTheDocument()
})

it('keeps unmapped owned parts discoverable without the compatibility category tree', async () => {
  vi.mocked(readHardwareTopology).mockResolvedValue({
    robot_id: 'robot',
    nodes: [],
    edges: [],
    roots: []
  })
  render(
    <RobotTopologyGraph
      {...props}
      relations={[
        { id: 'ownership', type: 'contains', from_entity_id: 'robot', to_entity_id: 'category' },
        {
          id: 'part-ownership',
          type: 'contains',
          from_entity_id: 'category',
          to_entity_id: 'motor'
        }
      ]}
    />
  )
  expect(await screen.findByText(/No mapped hardware topology/)).toBeInTheDocument()
  enter('robot')
  expect(screen.getByTestId('graph-node-motor')).toBeInTheDocument()
  expect(screen.queryByTestId('graph-node-category')).not.toBeInTheDocument()
})

it('recovers an unavailable topology on explicit retry and reports unknown software honestly', async () => {
  vi.mocked(readHardwareTopology).mockRejectedValueOnce(new Error('offline'))
  render(<RobotTopologyGraph {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Retry topology' }))
  await screen.findByRole('button', { name: 'Actuators / motors' })
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  enter('robot')
  expect(screen.getByText('Software: unknown')).toBeInTheDocument()
})

it('enters either robot through one shared host identity and keeps downstream buses scoped', async () => {
  const second = {
    ...topology,
    robot_id: 'robot-two',
    nodes: topology.nodes.filter((node) => ['host', 'bus', 'sensor'].includes(node.id)),
    edges: topology.edges.filter((edge) => edge.target === 'bus' || edge.target === 'sensor')
  }
  const first = {
    ...topology,
    nodes: topology.nodes.filter((node) => node.id !== 'sensor'),
    edges: topology.edges.filter((edge) => edge.target !== 'sensor')
  }
  vi.mocked(readHardwareTopology).mockImplementation(
    async (_project, robot) =>
      (robot === 'robot-two' ? second : first) as Awaited<ReturnType<typeof readHardwareTopology>>
  )
  const onSelect = vi.fn()
  render(
    <RobotTopologyGraph
      {...props}
      entities={[...entities, entity('robot-two', 'physical_robot')]}
      onSelect={onSelect}
    />
  )
  await screen.findByRole('button', { name: 'Sensors' })
  fireEvent.wheel(screen.getByRole('button', { name: 'Select robot-two' }), { deltaY: -100 })
  expect(screen.getAllByTestId('graph-node-host')).toHaveLength(1)
  enter('host')
  enter('bus')
  expect(screen.getByTestId('graph-node-sensor')).toBeInTheDocument()
  expect(screen.queryByTestId('graph-node-controller')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Select sensor' }))
  expect(onSelect.mock.calls.at(-1)?.[1].map((step: { entity: Entity }) => step.entity.id)).toEqual(
    ['robot-two', 'host', 'bus']
  )
  fireEvent.click(screen.getByRole('button', { name: 'Back to bus' }))
  fireEvent.click(screen.getByRole('button', { name: 'Back to host' }))
  fireEvent.click(screen.getByRole('button', { name: 'Back to robot-two' }))
  enter('robot')
  enter('host')
  enter('bus')
  expect(screen.getByTestId('graph-node-controller')).toBeInTheDocument()
  expect(screen.queryByTestId('graph-node-sensor')).not.toBeInTheDocument()
})

it('reveals a target in another robot while a shared-host scope is active', async () => {
  const second = {
    ...topology,
    robot_id: 'robot-two',
    nodes: topology.nodes.filter((node) => ['host', 'bus', 'sensor'].includes(node.id)),
    edges: topology.edges.filter((edge) => edge.target === 'bus' || edge.target === 'sensor')
  }
  const first = {
    ...topology,
    nodes: topology.nodes.filter((node) => node.id !== 'sensor'),
    edges: topology.edges.filter((edge) => edge.target !== 'sensor')
  }
  vi.mocked(readHardwareTopology).mockImplementation(
    async (_project, robot) =>
      (robot === 'robot-two' ? second : first) as Awaited<ReturnType<typeof readHardwareTopology>>
  )
  const onSelect = vi.fn()
  const combined = [...entities, entity('robot-two', 'physical_robot')]
  const view = render(<RobotTopologyGraph {...props} entities={combined} onSelect={onSelect} />)
  await screen.findByRole('button', { name: 'Sensors' })
  enter('robot')
  enter('host')
  enter('bus')
  expect(screen.queryByTestId('graph-node-sensor')).not.toBeInTheDocument()
  view.rerender(
    <RobotTopologyGraph
      {...props}
      entities={combined}
      onSelect={onSelect}
      reveal={{ entityId: 'sensor', sequence: 1 }}
    />
  )
  expect(await screen.findByTestId('graph-node-sensor')).toBeInTheDocument()
  expect(screen.queryByTestId('graph-node-controller')).not.toBeInTheDocument()
  expect(onSelect.mock.calls.at(-1)?.[1].map((step: { entity: Entity }) => step.entity.id)).toEqual(
    ['robot-two', 'host', 'bus']
  )
})
