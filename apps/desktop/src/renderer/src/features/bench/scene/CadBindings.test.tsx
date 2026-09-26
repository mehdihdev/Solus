import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { CadBindings } from './CadBindings'
import { cadSources, bindCad } from './cadApi'
import type { SceneModel } from './types'
vi.mock('./cadApi', () => ({ cadSources: vi.fn(), bindCad: vi.fn() }))
const model: SceneModel = {
  id: 'm',
  robot_id: 'r',
  name: 'Arm',
  version: 1,
  artifact_id: 'a',
  source_entity_id: null,
  source_revision: null,
  source_current: true,
  bindings: [],
  model: {
    links: [],
    joints: [],
    warnings: [],
    meshes: { mesh: { vertices: [0, 0, 0, 1, 0, 0, 0, 1, 0] } }
  }
}
it('requires explicit mesh association and queues exactly that reviewed source', async () => {
  vi.mocked(cadSources).mockResolvedValue([
    { id: 's', name: 'Gripper', observed_microversion: 'v2' }
  ])
  vi.mocked(bindCad).mockResolvedValue({ model, refresh_status: 'queued', job_id: null })
  const onSaved = vi.fn()
  render(<CadBindings projectId="p" model={model} onSaved={onSaved} />)
  fireEvent.click(screen.getByRole('button', { name: 'Link CAD geometry' }))
  const source = await screen.findByLabelText('CAD source for mesh')
  expect(bindCad).not.toHaveBeenCalled()
  fireEvent.change(source, { target: { value: 's' } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm CAD links' }))
  expect(await screen.findByText('CAD refresh queued.')).toBeInTheDocument()
  expect(bindCad).toHaveBeenCalledWith('p', 'm', 1, [{ mesh_key: 'mesh', source_entity_id: 's' }])
  expect(onSaved).toHaveBeenCalledOnce()
})
it('refuses confirmation when model version changes during review', async () => {
  vi.mocked(cadSources).mockResolvedValue([
    { id: 's', name: 'Gripper', observed_microversion: 'v2' }
  ])
  const view = render(<CadBindings projectId="p" model={model} onSaved={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Link CAD geometry' }))
  await screen.findByLabelText('CAD source for mesh')
  view.rerender(<CadBindings projectId="p" model={{ ...model, version: 2 }} onSaved={() => {}} />)
  expect(screen.getByRole('button', { name: 'Confirm CAD links' })).toBeDisabled()
})
it('can remove links when their CAD source is unavailable', async () => {
  vi.mocked(cadSources).mockResolvedValue([])
  vi.mocked(bindCad).mockResolvedValue({ model, refresh_status: 'current', job_id: null })
  render(
    <CadBindings
      projectId="p"
      model={{
        ...model,
        cad_bindings: [{ mesh_key: 'mesh', source_entity_id: 'gone', observed_microversion: 'v1' }]
      }}
      onSaved={() => {}}
    />
  )
  fireEvent.click(screen.getByRole('button', { name: 'Link CAD geometry' }))
  expect(
    await screen.findByRole('option', { name: 'Linked CAD source unavailable' })
  ).toBeDisabled()
  expect(screen.getByLabelText('CAD source for mesh')).toHaveValue('gone')
  fireEvent.change(screen.getByLabelText('CAD source for mesh'), { target: { value: '' } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm CAD links' }))
  expect(await screen.findByText('CAD links removed.')).toBeInTheDocument()
  expect(bindCad).toHaveBeenLastCalledWith('p', 'm', 1, [])
})
