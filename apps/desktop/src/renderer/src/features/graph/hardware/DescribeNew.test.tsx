import { beforeEach, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as hardware from '../../../lib/api/hardware'
import * as robotsApi from '../../../lib/api/physicalRobots'
import type { Entity } from '../../../lib/api/resources'
import { createUnassignedPart } from './createUnassignedPart'
import { DescribeNew } from './DescribeNew'

vi.mock('../../../lib/api/hardware', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/hardware')>()),
  createHardwarePart: vi.fn()
}))
vi.mock('./createUnassignedPart', () => ({ createUnassignedPart: vi.fn() }))
vi.mock('../../../lib/api/physicalRobots', () => ({ createPhysicalRobot: vi.fn() }))

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
const gantry: Entity = { ...robot, id: 'robot-2', name: 'Gantry' }
const part: Entity = { ...robot, id: 'part-1', name: 'Wrist IMU', type: 'part' }
const onCreated = vi.fn()

function renderDescribe(
  robots: Entity[] = [robot],
  mode: 'Guide' | 'Expert' = 'Guide',
  disabled = false
): void {
  render(
    <DescribeNew
      projectId="p1"
      mode={mode}
      robots={robots}
      onCreated={onCreated}
      disabled={disabled}
    />
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(createUnassignedPart).mockResolvedValue(part)
  vi.mocked(hardware.createHardwarePart).mockResolvedValue({ entity: part, config_entry_id: 'e' })
  vi.mocked(robotsApi.createPhysicalRobot).mockResolvedValue({ ...robot, id: 'robot-new' })
})

it('guesses the category as the user types, says so, and lets them change it', async () => {
  renderDescribe()
  const add = screen.getByRole('button', { name: 'Add' })
  expect(add).toBeDisabled()
  await userEvent.type(screen.getByRole('textbox', { name: 'What is it?' }), 'Wrist IMU')
  expect(screen.getByText('guessed')).toBeInTheDocument()
  const category = screen.getByRole('combobox', { name: 'Category' })
  expect(category).toHaveValue('sensors')
  await userEvent.selectOptions(category, 'actuators')
  expect(screen.queryByText('guessed')).not.toBeInTheDocument()
  await userEvent.click(add)
  expect(hardware.createHardwarePart).toHaveBeenCalledExactlyOnceWith('p1', 'robot-1', {
    name: 'Wrist IMU',
    category: 'actuators',
    specs: {},
    lifecycle: 'planned'
  })
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(part))
  expect(screen.getByRole('textbox', { name: 'What is it?' })).toHaveValue('')
  expect(robotsApi.createPhysicalRobot).not.toHaveBeenCalled()
})

it('re-guesses when the name changes until the user has chosen a category', async () => {
  renderDescribe()
  const name = screen.getByRole('textbox', { name: 'What is it?' })
  await userEvent.type(name, 'servo')
  expect(screen.getByRole('combobox', { name: 'Category' })).toHaveValue('actuators')
  await userEvent.clear(name)
  await userEvent.type(name, 'lipo')
  expect(screen.getByRole('combobox', { name: 'Category' })).toHaveValue('power')
})

it('targets the chosen robot when several exist', async () => {
  renderDescribe([robot, gantry])
  await userEvent.type(screen.getByRole('textbox', { name: 'What is it?' }), 'bracket')
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Part of' }), 'robot-2')
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  expect(hardware.createHardwarePart).toHaveBeenCalledWith(
    'p1',
    'robot-2',
    expect.objectContaining({ name: 'bracket', category: 'structure' })
  )
})

it('with no robot, creates an unassigned part in one click without a hidden robot', async () => {
  renderDescribe([])
  await userEvent.type(screen.getByRole('textbox', { name: 'What is it?' }), 'Wrist IMU')
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  expect(createUnassignedPart).toHaveBeenCalledWith(
    'p1',
    'Wrist IMU',
    'sensors',
    expect.any(String)
  )
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(part))
  expect(robotsApi.createPhysicalRobot).not.toHaveBeenCalled()
})

it('shows the failure verbatim and keeps the draft', async () => {
  vi.mocked(hardware.createHardwarePart).mockRejectedValueOnce(new Error('Part cap reached'))
  renderDescribe()
  await userEvent.type(screen.getByRole('textbox', { name: 'What is it?' }), 'pump')
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Part cap reached')
  expect(screen.getByRole('textbox', { name: 'What is it?' })).toHaveValue('pump')
  expect(onCreated).not.toHaveBeenCalled()
})

it('reads the SOL mode for its copy and honours disabled', () => {
  renderDescribe([robot], 'Guide')
  expect(
    screen.getByText(/Specs come later — from SOL, from a datasheet, or never\./)
  ).toBeInTheDocument()
})

it('is terse in Expert mode and inert offline', () => {
  renderDescribe([robot], 'Expert', true)
  expect(screen.queryByText(/from a datasheet/)).not.toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: 'What is it?' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled()
})

it('keeps guidance available inside compact options without pushing Add below the fold', () => {
  render(
    <DescribeNew
      projectId="p1"
      mode="Guide"
      robots={[robot]}
      onCreated={onCreated}
      disabled={false}
      compact
    />
  )
  const guidance = screen.getByText(/Specs come later/)
  expect(guidance.closest('details')).not.toHaveAttribute('open')
  expect(guidance.closest('details')).not.toBeNull()
  expect(screen.getByRole('button', { name: 'Add' }).closest('details')).toBeNull()
})
