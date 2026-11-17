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
it('shows a brain as wired and mounts no onboarding card on it (SOLUSDEV-326)', async () => {
  render(<RobotTopologyGraph {...props} />)
  await screen.findByRole('button', { name: 'Actuators / motors' })
  enter('robot')
  enter('host')
  enter('bus')
  const controller = within(screen.getByTestId('graph-node-controller'))
  expect(controller.getByText('Channel: usb_serial')).toBeInTheDocument()
  expect(controller.queryByRole('button', { name: 'Connect this computer' })).toBeNull()
  expect(controller.queryByRole('region')).toBeNull()
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
  // The wheel only enters a node whose children are indexed; on a slow CI runner the category
  // buttons can render before robot-two's children do, so wait for its zoom affordance first.
  await screen.findByRole('button', { name: 'Zoom into robot-two' })
  fireEvent.wheel(screen.getByRole('button', { name: 'Select robot-two' }), { deltaY: -100 })
  expect(await screen.findAllByTestId('graph-node-host')).toHaveLength(1)
  enter('host')
  enter('bus')
  expect(screen.getByTestId('graph-node-sensor')).toBeInTheDocument()
  expect(screen.queryByTestId('graph-node-controller')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Select sensor' }))
  expect(onSelect.mock.calls.at(-1)?.[1].map((step: { entity: Entity }) => step.entity.id)).toEqual(
    ['robot-two', 'host', 'bus']
  )
  fireEvent.click(screen.getByRole('button', { name: 'Zoom out (Esc)' }))
  fireEvent.click(screen.getByRole('button', { name: 'Zoom out (Esc)' }))
  fireEvent.click(screen.getByRole('button', { name: 'Zoom out (Esc)' }))
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

it('draws a part shared by two brains once, under its first parent, with a cross-link', async () => {
  const dag = {
    robot_id: 'robot',
    roots: ['controller', 'downstream'],
    nodes: [
      ['controller', 'brain'],
      ['bus', 'bus'],
      ['downstream', 'brain'],
      ['sensor', 'part']
    ].map(([id, role]) => ({ id, name: id, role, brain_kind: role === 'brain' ? 'mcu' : null })),
    edges: [
      ['controller', 'bus'],
      ['bus', 'sensor'],
      ['downstream', 'sensor']
    ].map(([source, target]) => ({ id: `${source}-${target}`, source, target }))
  }
  vi.mocked(readHardwareTopology).mockResolvedValue(
    dag as Awaited<ReturnType<typeof readHardwareTopology>>
  )
  render(<RobotTopologyGraph {...props} />)
  await screen.findByRole('button', { name: 'Zoom into robot' })
  enter('robot')
  expect(screen.getByTestId('graph-node-controller')).toBeInTheDocument()
  expect(screen.getByTestId('graph-node-downstream')).toBeInTheDocument()
  // The second parent is drawn as a cross-link between the two brains, not a second copy.
  expect(document.querySelectorAll('.graph-cross-edge').length).toBeGreaterThan(0)
  enter('controller')
  enter('bus')
  expect(screen.getAllByTestId('graph-node-sensor')).toHaveLength(1)
})
