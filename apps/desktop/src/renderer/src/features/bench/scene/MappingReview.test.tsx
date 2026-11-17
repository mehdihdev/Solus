import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { getHardwareConfig, type HardwareConfigOut } from '../../../lib/api/hardware'
import { MappingReview } from './MappingReview'
import { confirmSceneMapping } from './sceneApi'
import type { SceneModel } from './types'
vi.mock('./sceneApi', () => ({ confirmSceneMapping: vi.fn() }))
vi.mock('../../../lib/api/hardware', () => ({
  getHardwareConfig: vi.fn().mockResolvedValue({ config: { bus_map: [] } })
}))
vi.mock('../../../lib/api/hardwareTopology', () => ({
  readHardwareTopology: vi.fn().mockResolvedValue({ nodes: [] })
}))
const model: SceneModel = {
  id: 'model',
  name: 'Arm',
  robot_id: 'robot',
  artifact_id: 'a',
  version: 1,
  source_entity_id: null,
  source_revision: null,
  source_current: true,
  bindings: [],
  model: { links: [], joints: [], warnings: [] }
}
it('invalidates a draft when a concurrent model version arrives', async () => {
  const view = render(<MappingReview projectId="p" model={model} onSaved={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Review joint mapping for Arm' }))
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Confirm joint mapping' })).toBeEnabled()
  )
  view.rerender(<MappingReview projectId="p" model={{ ...model, version: 2 }} onSaved={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Confirm joint mapping' })).toBeDisabled()
  expect(screen.getByText(/Model changed/)).toBeInTheDocument()
  expect(confirmSceneMapping).not.toHaveBeenCalled()
})

// SOLUSDEV-326: each part's device key is on the brain its bus row names; a row without one
// sits on the robot's only brain.
it('keys each mapped part to the brain its bus row sits behind', async () => {
  const joint = {
    name: 'shoulder',
    type: 'revolute' as const,
    parent: 'base',
    child: 'arm',
    xyz: [0, 0, 0],
    rpy: [0, 0, 0],
    axis: [0, 0, 1],
    lower: null,
    upper: null
  }
  const config = {
    schema_version: 1,
    robot_entity_id: 'robot',
    identity: { kind: 'usb_can', binding: 'AAA' },
    bus_map: [
      { protocol: 'bus', address: '1', part_entity_id: 'left', brain: 'can:AAA' },
      { protocol: 'bus', address: '1', part_entity_id: 'right', brain: 'usb:BBB' }
    ]
  } as HardwareConfigOut['config']
  vi.mocked(getHardwareConfig).mockResolvedValueOnce({
    entry_id: 'entry',
    robot_entity_id: 'robot',
    config
  })
  render(
    <MappingReview
      projectId="p"
      model={{ ...model, model: { ...model.model, joints: [joint] } }}
      onSaved={vi.fn()}
    />
  )
  fireEvent.click(screen.getByRole('button', { name: 'Review joint mapping for Arm' }))
  const select = screen.getByRole('combobox', { name: 'shoulder hardware part' })
  await waitFor(() =>
    expect(
      within(select)
        .getAllByRole('option')
        .map((option) => option.textContent)
    ).toEqual(['Unmapped', 'left · can:AAA/1', 'right · usb:BBB/1'])
  )
})

it('keys a row without a brain to the robot’s one identity', async () => {
  const joint = {
    name: 'elbow',
    type: 'revolute' as const,
    parent: 'arm',
    child: 'hand',
    xyz: [0, 0, 0],
    rpy: [0, 0, 0],
    axis: [0, 0, 1],
    lower: null,
    upper: null
  }
  vi.mocked(getHardwareConfig).mockResolvedValueOnce({
    entry_id: 'entry',
    robot_entity_id: 'robot',
    config: {
      schema_version: 1,
      robot_entity_id: 'robot',
      identity: { kind: 'usb_can', binding: 'AAA' },
      bus_map: [{ protocol: 'bus', address: '2', part_entity_id: 'wrist' }]
    } as HardwareConfigOut['config']
  })
  render(
    <MappingReview
      projectId="p"
      model={{ ...model, model: { ...model.model, joints: [joint] } }}
      onSaved={vi.fn()}
    />
  )
  fireEvent.click(screen.getByRole('button', { name: 'Review joint mapping for Arm' }))
  const select = screen.getByRole('combobox', { name: 'elbow hardware part' })
  await waitFor(() =>
    expect(within(select).getByRole('option', { name: 'wrist · can:AAA/2' })).toBeInTheDocument()
  )
})
