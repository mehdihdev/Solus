import { beforeEach, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as hardware from '../../../lib/api/hardware'
import * as robotsApi from '../../../lib/api/physicalRobots'
import type { Entity } from '../../../lib/api/resources'
import { ApiError } from '../../../lib/api/envelope.types'
import { HardwareSearch } from './HardwareSearch'

vi.mock('../../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/hardware')>()),
  searchLibrary: vi.fn(),
  getLibraryDefinition: vi.fn(),
  importLibraryPlatform: vi.fn(),
  importLibraryPart: vi.fn()
}))
vi.mock('../../../lib/api/physicalRobots', () => ({ createPhysicalRobot: vi.fn() }))

const robot: Entity = {
  id: 'robot-1',
  project_id: 'p1',
  name: 'Rover',
  type: 'physical_robot',
  domain: 'project',
  source_key: '',
  origin: 'manual',
  version: 1
}
const gantry: Entity = { ...robot, id: 'robot-2', name: 'Gantry' }
const partEntity: Entity = { ...robot, id: 'part-9', name: 'Demo bus servo', type: 'part' }
const hits: hardware.LibraryHit[] = [
  {
    kind: 'part',
    id: 'demo-servo',
    name: 'Demo bus servo',
    manufacturer: 'Demo Labs',
    category: 'actuators',
    machine_class: null,
    summary: 'actuators · driver demo-bus'
  },
  {
    kind: 'platform',
    id: 'demo-arm',
    name: 'Demo arm',
    manufacturer: 'Demo Labs',
    category: null,
    machine_class: 'arm',
    summary: 'arm · usb_serial · 3 parts'
  }
]
const servo: hardware.LibraryPartDefinition = {
  kind: 'part',
  id: 'demo-servo',
  name: 'Demo bus servo',
  manufacturer: 'Demo Labs',
  keywords: ['servo'],
  notes: 'Daisy-chained on one half-duplex bus.',
  category: 'actuators',
  specs: { interface: 'serial bus', supply_v: 12 },
  driver_id: 'demo-bus',
  protocol_version: 1,
  resolution: 4096,
  register_map: {},
  telemetry: [{ quantity: 'position', unit: 'raw' }],
  calibration_mode: 'degrees',
  datasheet_url: null
}
const onCreated = vi.fn()

function renderSearch(robots: Entity[] = [robot], disabled = false): void {
  render(
    <HardwareSearch projectId="p1" robots={robots} onCreated={onCreated} disabled={disabled} />
  )
}
const row = (name: string): ReturnType<typeof within> =>
  within(screen.getByRole('listitem', { name }))

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(hardware.searchLibrary).mockResolvedValue(hits)
  vi.mocked(hardware.getLibraryDefinition).mockResolvedValue(servo)
  vi.mocked(hardware.importLibraryPlatform).mockResolvedValue({
    robot: { ...robot, id: 'robot-new', name: 'Demo arm' },
    part_ids: ['a', 'b', 'c'],
    config_entry_id: 'entry',
    suggestion_ids: []
  })
  vi.mocked(hardware.importLibraryPart).mockResolvedValue({
    entity: partEntity,
    config_entry_id: 'entry'
  })
  vi.mocked(robotsApi.createPhysicalRobot).mockResolvedValue({ ...robot, id: 'robot-named' })
})

it('shows the seed on an empty query as a flat list with kind labels, then searches debounced', async () => {
  renderSearch()
  const box = screen.getByRole('searchbox', { name: 'Search parts and platforms' })
  expect(box).toHaveAttribute(
    'placeholder',
    'Search parts and platforms — e.g. a servo model, a platform, a sensor'
  )
  expect(await screen.findByRole('listitem', { name: 'Demo bus servo' })).toBeInTheDocument()
  expect(row('Demo bus servo').getByText('part')).toBeInTheDocument()
  expect(row('Demo bus servo').getByText('actuators · driver demo-bus')).toBeInTheDocument()
  expect(row('Demo arm').getByText('platform')).toBeInTheDocument()
  expect(hardware.searchLibrary).toHaveBeenCalledExactlyOnceWith('p1', '')
  await userEvent.type(box, 'arm')
  await waitFor(() => expect(hardware.searchLibrary).toHaveBeenLastCalledWith('p1', 'arm'))
  expect(hardware.searchLibrary).toHaveBeenCalledTimes(2)
})

it('says honestly when nothing matches and shows a search failure verbatim', async () => {
  vi.mocked(hardware.searchLibrary).mockResolvedValueOnce([])
  renderSearch()
  expect(await screen.findByText('Nothing in the library matches.')).toBeInTheDocument()
  vi.mocked(hardware.searchLibrary).mockRejectedValueOnce(
    new ApiError(503, 'source_unavailable', 'library is not available on this server')
  )
  await userEvent.type(screen.getByRole('searchbox'), 'x')
  expect(await screen.findByRole('alert')).toHaveTextContent('library is not available')
})

it('adds a platform as a new robot with an optional name and reports a pending suggestion', async () => {
  vi.mocked(hardware.importLibraryPlatform).mockResolvedValueOnce({
    robot: { ...robot, id: 'robot-new', name: 'Demo arm' },
    part_ids: ['a'],
    config_entry_id: 'entry',
    suggestion_ids: ['s1']
  })
  renderSearch()
  await userEvent.click(await screen.findByRole('button', { name: 'Add Demo arm as new robot' }))
  const name = row('Demo arm').getByRole('textbox', { name: 'Robot name' })
  expect(name).toHaveValue('')
  expect(name).toHaveAttribute('placeholder', 'Demo arm')
  await userEvent.click(row('Demo arm').getByRole('button', { name: 'Add' }))
  expect(hardware.importLibraryPlatform).toHaveBeenCalledExactlyOnceWith(
    'p1',
    'demo-arm',
    undefined
  )
  await waitFor(() =>
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: 'robot-new' }))
  )
  expect(
    screen.getByText('A link suggestion is pending — the device card offers it.')
  ).toBeInTheDocument()
  expect(screen.queryByText(/s1/)).not.toBeInTheDocument()
})

it('sends a typed platform name and shows an import failure verbatim', async () => {
  vi.mocked(hardware.importLibraryPlatform).mockRejectedValueOnce(new Error('Robot cap reached'))
  renderSearch()
  await userEvent.click(await screen.findByRole('button', { name: 'Add Demo arm as new robot' }))
  await userEvent.type(row('Demo arm').getByRole('textbox', { name: 'Robot name' }), ' Bench ')
  await userEvent.click(row('Demo arm').getByRole('button', { name: 'Add' }))
  expect(hardware.importLibraryPlatform).toHaveBeenCalledWith('p1', 'demo-arm', 'Bench')
  expect(await screen.findByRole('alert')).toHaveTextContent('Robot cap reached')
  expect(onCreated).not.toHaveBeenCalled()
})

it('adds a part to the only robot, preselected, in its default category', async () => {
  renderSearch()
  const servoRow = within(await screen.findByRole('listitem', { name: 'Demo bus servo' }))
  expect(servoRow.getByRole('combobox', { name: 'Part of' })).toHaveValue('robot-1')
  await userEvent.click(servoRow.getByRole('button', { name: 'Add to Rover' }))
  expect(hardware.importLibraryPart).toHaveBeenCalledExactlyOnceWith('p1', 'demo-servo', {
    robot_id: 'robot-1'
  })
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(partEntity))
  expect(robotsApi.createPhysicalRobot).not.toHaveBeenCalled()
})

it('lets the user pick among several robots', async () => {
  renderSearch([robot, gantry])
  const servoRow = within(await screen.findByRole('listitem', { name: 'Demo bus servo' }))
  await userEvent.selectOptions(servoRow.getByRole('combobox', { name: 'Part of' }), 'robot-2')
  await userEvent.click(servoRow.getByRole('button', { name: 'Add to Gantry' }))
  expect(hardware.importLibraryPart).toHaveBeenCalledWith('p1', 'demo-servo', {
    robot_id: 'robot-2'
  })
})

it('with no robot, a part becomes the first part of a new robot named by the user', async () => {
  renderSearch([])
  const servoRow = within(await screen.findByRole('listitem', { name: 'Demo bus servo' }))
  await userEvent.type(servoRow.getByRole('textbox', { name: 'New robot name' }), 'Bench')
  await userEvent.click(servoRow.getByRole('button', { name: 'Add to a new robot' }))
  expect(robotsApi.createPhysicalRobot).toHaveBeenCalledExactlyOnceWith('p1', undefined, 'Bench')
  await waitFor(() =>
    expect(hardware.importLibraryPart).toHaveBeenCalledWith('p1', 'demo-servo', {
      robot_id: 'robot-named'
    })
  )
  await waitFor(() =>
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: 'robot-named' }))
  )
})

it('opens a details disclosure that lazily reads the definition and lists its specs', async () => {
  renderSearch()
  await screen.findByRole('listitem', { name: 'Demo bus servo' })
  expect(hardware.getLibraryDefinition).not.toHaveBeenCalled()
  await userEvent.click(row('Demo bus servo').getByRole('button', { name: 'Details' }))
  expect(hardware.getLibraryDefinition).toHaveBeenCalledExactlyOnceWith('p1', 'part', 'demo-servo')
  const specs = within(await row('Demo bus servo').findByRole('list', { name: 'Specs' }))
  expect(specs.getByText('interface')).toBeInTheDocument()
  expect(specs.getByText('serial bus')).toBeInTheDocument()
  expect(specs.getByText('resolution')).toBeInTheDocument()
  expect(specs.getByText('position (raw)')).toBeInTheDocument()
  expect(
    row('Demo bus servo').getByText('Daisy-chained on one half-duplex bus.')
  ).toBeInTheDocument()
})

it('disables every control while offline', async () => {
  renderSearch([robot], true)
  expect(screen.getByRole('searchbox')).toBeDisabled()
  await screen.findByRole('listitem', { name: 'Demo bus servo' })
  expect(screen.getByRole('button', { name: 'Add to Rover' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Add Demo arm as new robot' })).toBeDisabled()
})
