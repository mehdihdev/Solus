import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
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
