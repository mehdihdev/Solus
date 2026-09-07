import { beforeEach, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as hardware from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import { ApiError } from '../../../lib/api/envelope.types'
import { AuthoredPartModal, authoredSpecs } from './AuthoredPartModal'

vi.mock('../../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/hardware')>()),
  createHardwarePart: vi.fn()
}))

const robot: Entity = {
  id: 'robot-1',
  project_id: 'p1',
  name: 'Rover',
  type: 'physical_robot',
  domain: 'project',
  source_key: '',
  source_id: null,
  origin: 'manual',
  version: 1
}
const part: Entity = { ...robot, id: 'part-1', name: 'Pressure sensor', type: 'part' }
const createRobot = vi.fn<() => Promise<string>>()
const onCreated = vi.fn()
const onClose = vi.fn()

function renderModal(robots: Entity[] = [robot], mode: 'Guide' | 'Expert' = 'Guide'): void {
  render(
    <AuthoredPartModal
      projectId="p1"
      robots={robots}
      mode={mode}
      createRobot={createRobot}
      onCreated={onCreated}
      onClose={onClose}
    />
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(hardware.createHardwarePart).mockResolvedValue({
    entity: part,
    config_entry_id: 'entry-1'
  })
  createRobot.mockResolvedValue('robot-new')
})

it('authors a pressure sensor under the chosen robot with parsed specs', async () => {
  renderModal()
  await userEvent.type(screen.getByRole('textbox', { name: 'Name' }), 'BMP-class pressure sensor')
  expect(screen.getByRole('combobox', { name: 'Robot' })).toHaveValue('robot-1')
  expect(screen.getByRole('combobox', { name: 'Category' })).toHaveValue('sensors')
  await userEvent.type(screen.getByRole('textbox', { name: 'Interface' }), 'I2C')
  await userEvent.type(screen.getByRole('spinbutton', { name: 'Supply (V)' }), '3.3')
  await userEvent.type(screen.getByRole('textbox', { name: 'Range' }), '300-1250 hPa')
  await userEvent.click(screen.getByRole('button', { name: 'Create' }))
  expect(hardware.createHardwarePart).toHaveBeenCalledExactlyOnceWith('p1', 'robot-1', {
    name: 'BMP-class pressure sensor',
    category: 'sensors',
    specs: { interface: 'I2C', supply_v: 3.3, range: '300-1250 hPa' },
    lifecycle: 'planned'
  })
  expect(createRobot).not.toHaveBeenCalled()
  expect(onCreated).toHaveBeenCalledExactlyOnceWith(part)
  expect(onClose).toHaveBeenCalledOnce()
})

it('authors an ESC under actuators with an ordered lifecycle and category-specific fields', async () => {
  renderModal()
  await userEvent.type(screen.getByRole('textbox', { name: 'Name' }), '  Drive ESC  ')
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Category' }), 'actuators')
  expect(screen.queryByRole('textbox', { name: 'Range' })).not.toBeInTheDocument()
  await userEvent.type(screen.getByRole('textbox', { name: 'Interface' }), 'PWM')
  await userEvent.type(screen.getByRole('textbox', { name: 'Rated output' }), '30 A')
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Lifecycle' }), 'ordered')
  await userEvent.click(screen.getByRole('button', { name: 'Create' }))
  expect(hardware.createHardwarePart).toHaveBeenCalledWith('p1', 'robot-1', {
    name: 'Drive ESC',
    category: 'actuators',
    specs: { interface: 'PWM', rated_output: '30 A' },
    lifecycle: 'ordered'
  })
})

it('creates a new Physical Robot first when no robot exists, then the part', async () => {
  renderModal([])
  const target = screen.getByRole('combobox', { name: 'Robot' })
  expect(target.querySelectorAll('option')).toHaveLength(1)
  expect(target).toHaveValue('__new__')
  await userEvent.type(screen.getByRole('textbox', { name: 'Name' }), 'Gripper valve')
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Category' }), 'end_effectors')
  await userEvent.click(screen.getByRole('button', { name: 'Create' }))
  expect(createRobot).toHaveBeenCalledOnce()
  expect(hardware.createHardwarePart).toHaveBeenCalledWith('p1', 'robot-new', {
    name: 'Gripper valve',
    category: 'end_effectors',
    specs: {},
    lifecycle: 'planned'
  })
  expect(onCreated).toHaveBeenCalledWith(part)
})

it('shows the server error, keeps the form, and never closes on failure', async () => {
  vi.mocked(hardware.createHardwarePart).mockRejectedValue(
    new ApiError(422, 'validation_error', 'specs: too many keys')
  )
  renderModal()
  await userEvent.type(screen.getByRole('textbox', { name: 'Name' }), 'Bad part')
  await userEvent.click(screen.getByRole('button', { name: 'Create' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('specs: too many keys')
  expect(screen.getByRole('textbox', { name: 'Name' })).toHaveValue('Bad part')
  expect(onCreated).not.toHaveBeenCalled()
  expect(onClose).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Create' })).toBeEnabled()
})

it('surfaces a robot creation failure without authoring the part', async () => {
  createRobot.mockRejectedValue(new Error('Cannot create robot'))
  renderModal([])
  await userEvent.type(screen.getByRole('textbox', { name: 'Name' }), 'Orphan part')
  await userEvent.click(screen.getByRole('button', { name: 'Create' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Cannot create robot')
  expect(hardware.createHardwarePart).not.toHaveBeenCalled()
})

it('disables Create for a blank name and shows busy status while creating', async () => {
  let finish: (value: { entity: Entity; config_entry_id: string }) => void = () => undefined
  vi.mocked(hardware.createHardwarePart).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  renderModal()
  const create = screen.getByRole('button', { name: 'Create' })
  expect(create).toBeDisabled()
  await userEvent.type(screen.getByRole('textbox', { name: 'Name' }), '   ')
  expect(create).toBeDisabled()
  expect(screen.getByRole('textbox', { name: 'Name' })).toHaveAttribute('maxlength', '512')
  await userEvent.type(screen.getByRole('textbox', { name: 'Name' }), 'Servo')
  await userEvent.click(create)
  expect(screen.getByText('Creating part…')).toHaveAttribute('role', 'status')
  expect(hardware.createHardwarePart).toHaveBeenCalledOnce()
  finish({ entity: part, config_entry_id: 'entry-1' })
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
})

it('switches copy with SOL mode', () => {
  renderModal([robot], 'Expert')
  expect(
    screen.getByText('Name, robot, category, specs, lifecycle. Only the name is required.')
  ).toBeInTheDocument()
})

it('parses numbers, drops blanks and ignores non-numeric number fields', () => {
  expect(
    authoredSpecs('power', { chemistry_or_type: ' LiPo ', voltage_v: '11.1', capacity: '' })
  ).toEqual({ chemistry_or_type: 'LiPo', voltage_v: 11.1 })
  expect(authoredSpecs('structure', { mass_g: 'heavy', unknown: 'x' })).toEqual({})
})
