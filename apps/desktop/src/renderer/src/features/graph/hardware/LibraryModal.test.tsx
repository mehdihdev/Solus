import { beforeEach, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as hardware from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import { ApiError } from '../../../lib/api/envelope.types'
import { HARDWARE_COPY } from './hardware.constants'
import { LibraryModal } from './LibraryModal'

vi.mock('../../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/hardware')>()),
  searchLibrary: vi.fn(),
  getLibraryDefinition: vi.fn(),
  importLibraryPlatform: vi.fn(),
  importLibraryPart: vi.fn()
}))

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
    kind: 'part',
    id: 'demo-imu',
    name: 'Demo IMU',
    manufacturer: null,
    category: 'sensors',
    machine_class: null,
    summary: 'sensors · no driver'
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
  specs: { interface: 'serial bus', supply_v: 12, stall_torque_kg_cm: 30 },
  driver_id: 'demo-bus',
  protocol_version: 1,
  resolution: 4096,
  register_map: {},
  telemetry: [{ quantity: 'position', unit: 'raw' }],
  calibration_mode: 'degrees',
  datasheet_url: null
}
const imu: hardware.LibraryPartDefinition = {
  ...servo,
  id: 'demo-imu',
  name: 'Demo IMU',
  manufacturer: null,
  notes: null,
  category: 'sensors',
  specs: { interface: 'I2C' },
  driver_id: null,
  calibration_mode: null
}
const slot = (
  address: string,
  role: string,
  gear_ratio: string | null
): hardware.LibraryPlatformPart => ({
  part: 'demo-servo',
  address,
  role,
  category: null,
  gear_ratio,
  calibration_mode: null,
  calibration: {}
})
const arm: hardware.LibraryPlatformDefinition = {
  kind: 'platform',
  id: 'demo-arm',
  name: 'Demo arm',
  manufacturer: 'Demo Labs',
  keywords: ['arm'],
  notes: null,
  machine_class: 'arm',
  transport: 'usb_serial',
  driver_id: 'demo-bus',
  params: { baud: 1000000 },
  parts: [
    slot('1', 'shoulder_pan', '1:345'),
    slot('2', 'shoulder_lift', '1:345'),
    { ...slot('6', 'gripper', null), category: 'end_effectors' }
  ],
  urdf: null,
  mjcf: null
}
const armNoGears: hardware.LibraryPlatformDefinition = {
  ...arm,
  parts: arm.parts.map((part) => ({ ...part, gear_ratio: null }))
}
const onCreated = vi.fn()
const onClose = vi.fn()

function renderModal(robots: Entity[] = [robot, gantry], mode: 'Guide' | 'Expert' = 'Guide'): void {
  render(
    <LibraryModal
      projectId="p1"
      mode={mode}
      robots={robots}
      onCreated={onCreated}
      onClose={onClose}
    />
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(hardware.searchLibrary).mockResolvedValue(hits)
  vi.mocked(hardware.getLibraryDefinition).mockImplementation(async (_project, kind, id) =>
    kind === 'platform' ? arm : id === 'demo-imu' ? imu : servo
  )
})

it('lists the seed as Parts and Platforms on open with the mode copy', async () => {
  renderModal()
  expect(screen.getByRole('status')).toHaveTextContent('Searching the library…')
  const parts = within(await screen.findByRole('list', { name: 'Parts' }))
  expect(parts.getAllByRole('button')).toHaveLength(2)
  expect(parts.getByRole('button', { name: /Demo bus servo/ })).toHaveTextContent(
    'actuators · driver demo-bus'
  )
  const platforms = within(screen.getByRole('list', { name: 'Platforms' }))
  expect(platforms.getByRole('button', { name: /Demo arm/ })).toBeInTheDocument()
  expect(screen.getByText(HARDWARE_COPY.library.Guide)).toBeInTheDocument()
  expect(hardware.searchLibrary).toHaveBeenCalledExactlyOnceWith('p1', '')
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

it('searches as the user types and says exactly when nothing matches', async () => {
  vi.mocked(hardware.searchLibrary).mockResolvedValueOnce(hits).mockResolvedValue([])
  renderModal([], 'Expert')
  await screen.findByRole('list', { name: 'Parts' })
  expect(screen.getByText(HARDWARE_COPY.library.Expert)).toBeInTheDocument()
  await userEvent.type(screen.getByRole('searchbox', { name: 'Search the library' }), 'nothing')
  expect(await screen.findByText('Nothing in the library matches.')).toBeInTheDocument()
  expect(hardware.searchLibrary).toHaveBeenLastCalledWith('p1', 'nothing')
  expect(screen.queryByRole('list')).not.toBeInTheDocument()
})

it('reports a search failure verbatim', async () => {
  vi.mocked(hardware.searchLibrary).mockRejectedValueOnce(
    new ApiError(503, 'source_unavailable', 'library unavailable')
  )
  renderModal()
  expect(await screen.findByRole('alert')).toHaveTextContent('library unavailable')
  expect(screen.queryByRole('list')).not.toBeInTheDocument()
})

it('previews a part with its category, specs and notes, and asks for a robot when there is none', async () => {
  renderModal([])
  await userEvent.click(await screen.findByRole('button', { name: /Demo bus servo/ }))
  expect(hardware.getLibraryDefinition).toHaveBeenCalledExactlyOnceWith('p1', 'part', 'demo-servo')
  const preview = within(await screen.findByRole('region', { name: 'Demo bus servo' }))
  expect(preview.getByText('Actuators / motors · Demo Labs · driver demo-bus')).toBeInTheDocument()
  expect(preview.getByText('serial bus')).toBeInTheDocument()
  expect(preview.getByText('stall_torque_kg_cm')).toBeInTheDocument()
  expect(preview.getByText('30')).toBeInTheDocument()
  expect(preview.getByText('Daisy-chained on one half-duplex bus.')).toBeInTheDocument()
  expect(
    preview.getByText('Create a Physical Robot first (Add › Hardware › Authored).')
  ).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^Import/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
})

it('imports a part into the chosen robot under the chosen category', async () => {
  vi.mocked(hardware.importLibraryPart).mockResolvedValue({
    entity: partEntity,
    config_entry_id: 'e1'
  })
  renderModal()
  await userEvent.click(await screen.findByRole('button', { name: /Demo bus servo/ }))
  const category = await screen.findByRole('combobox', { name: 'Category' })
  expect(category).toHaveValue('actuators')
  expect(screen.getByRole('button', { name: 'Import into Rover' })).toBeEnabled()
  await userEvent.selectOptions(category, 'end_effectors')
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Robot' }), 'robot-2')
  await userEvent.click(screen.getByRole('button', { name: 'Import into Gantry' }))
  expect(hardware.importLibraryPart).toHaveBeenCalledExactlyOnceWith('p1', 'demo-servo', {
    robot_id: 'robot-2',
    category: 'end_effectors'
  })
  expect(await screen.findByRole('status')).toHaveTextContent('Imported — 1 part')
  expect(onCreated).toHaveBeenCalledExactlyOnceWith(partEntity)
  expect(onClose).not.toHaveBeenCalled()
})

it('defaults the category to each selected definition', async () => {
  renderModal()
  await userEvent.click(await screen.findByRole('button', { name: /Demo bus servo/ }))
  expect(await screen.findByRole('combobox', { name: 'Category' })).toHaveValue('actuators')
  await userEvent.click(screen.getByRole('button', { name: /Demo IMU/ }))
  await screen.findByRole('region', { name: 'Demo IMU' })
  expect(screen.getByRole('combobox', { name: 'Category' })).toHaveValue('sensors')
  expect(screen.getByText('Sensors · no driver')).toBeInTheDocument()
})

it('previews a platform with its parts and gear ratios, imports it named, and reports the pending suggestion', async () => {
  vi.mocked(hardware.importLibraryPlatform).mockResolvedValue({
    robot: { ...robot, id: 'robot-new', name: 'Left arm' },
    part_ids: ['a', 'b', 'c'],
    config_entry_id: 'e1',
    suggestion_ids: ['sg1']
  })
  renderModal([])
  await userEvent.click(await screen.findByRole('button', { name: /Demo arm/ }))
  expect(hardware.getLibraryDefinition).toHaveBeenCalledExactlyOnceWith(
    'p1',
    'platform',
    'demo-arm'
  )
  const preview = within(await screen.findByRole('region', { name: 'Demo arm' }))
  expect(preview.getByText('arm · usb_serial · Demo Labs · driver demo-bus')).toBeInTheDocument()
  const parts = within(preview.getByRole('list', { name: 'Platform parts' }))
  expect(parts.getAllByRole('listitem')).toHaveLength(3)
  expect(parts.getByText('shoulder_pan')).toBeInTheDocument()
  expect(parts.getByText('demo-servo @ 6 · end_effectors')).toBeInTheDocument()
  const gears = within(preview.getByRole('table', { name: 'Gear ratios' }))
  expect(gears.getAllByRole('row')).toHaveLength(3)
  expect(gears.getAllByText('1:345')).toHaveLength(2)
  await userEvent.type(preview.getByRole('textbox', { name: 'Robot name' }), ' Left arm ')
  await userEvent.click(preview.getByRole('button', { name: 'Import as new robot' }))
  expect(hardware.importLibraryPlatform).toHaveBeenCalledExactlyOnceWith(
    'p1',
    'demo-arm',
    'Left arm'
  )
  expect(await screen.findByRole('status')).toHaveTextContent('Imported — 3 parts')
  expect(
    screen.getByText('A link suggestion is pending — Add › Hardware › Detected shows it.')
  ).toBeInTheDocument()
  expect(onCreated).toHaveBeenCalledExactlyOnceWith(
    expect.objectContaining({ id: 'robot-new', name: 'Left arm' })
  )
  expect(screen.queryByRole('button', { name: 'Import as new robot' })).not.toBeInTheDocument()
})

it('imports a platform under its own name, with no gear table or suggestion line when there are none', async () => {
  vi.mocked(hardware.getLibraryDefinition).mockResolvedValueOnce(armNoGears)
  vi.mocked(hardware.importLibraryPlatform).mockResolvedValue({
    robot,
    part_ids: ['a'],
    config_entry_id: 'e1',
    suggestion_ids: []
  })
  renderModal()
  await userEvent.click(await screen.findByRole('button', { name: /Demo arm/ }))
  const preview = within(await screen.findByRole('region', { name: 'Demo arm' }))
  expect(preview.queryByRole('table')).not.toBeInTheDocument()
  expect(preview.getByRole('textbox', { name: 'Robot name' })).toHaveAttribute(
    'placeholder',
    'Demo arm'
  )
  await userEvent.click(preview.getByRole('button', { name: 'Import as new robot' }))
  expect(hardware.importLibraryPlatform).toHaveBeenCalledExactlyOnceWith(
    'p1',
    'demo-arm',
    undefined
  )
  expect(await screen.findByRole('status')).toHaveTextContent('Imported — 1 part')
  expect(screen.queryByText(/link suggestion/)).not.toBeInTheDocument()
})

it('surfaces import and preview failures verbatim and keeps the list', async () => {
  vi.mocked(hardware.importLibraryPart).mockRejectedValue(
    new ApiError(404, 'not_found', 'part definition not found')
  )
  renderModal()
  await userEvent.click(await screen.findByRole('button', { name: /Demo bus servo/ }))
  await userEvent.click(await screen.findByRole('button', { name: 'Import into Rover' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('part definition not found')
  expect(onCreated).not.toHaveBeenCalled()
  vi.mocked(hardware.getLibraryDefinition).mockRejectedValueOnce(new Error('API unreachable'))
  await userEvent.click(screen.getByRole('button', { name: /Demo IMU/ }))
  expect(await screen.findByRole('alert')).toHaveTextContent('API unreachable')
  expect(screen.getByRole('list', { name: 'Parts' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(onClose).toHaveBeenCalledOnce()
})
