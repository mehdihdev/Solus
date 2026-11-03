import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as workspaceSession from '../../graph/workspaceSession'
import { ScenePanel } from './ScenePanel'
import { listSceneModels, importSceneModel } from './sceneApi'
import { listEntities, uploadArtifact } from '../../../lib/api/resources'
vi.mock('./SceneViewer', () => ({ SceneViewer: () => <div>3D scene</div> }))
vi.mock('./sceneApi', () => ({
  listSceneModels: vi.fn(),
  importSceneModel: vi.fn(),
  confirmSceneMapping: vi.fn()
}))
vi.mock('../../../lib/api/resources', () => ({
  listEntities: vi.fn(),
  uploadArtifact: vi.fn(),
  getBenchDeviceRecent: vi.fn()
}))
const robot = {
  id: 'robot',
  name: 'Bench robot',
  project_id: 'p',
  type: 'physical_robot',
  domain: 'hardware',
  source_key: null
}
beforeEach(() => {
  vi.mocked(listSceneModels).mockResolvedValue([])
  vi.mocked(listEntities).mockResolvedValue([robot])
})
describe('scene import', () => {
  it('requires a selected local model and robot before upload', async () => {
    render(<ScenePanel projectId="p" />)
    await screen.findByRole('option', { name: 'Bench robot' })
    expect(screen.getByRole('button', { name: 'Import model' })).toBeDisabled()
    expect(uploadArtifact).not.toHaveBeenCalled()
  })
  it('uploads only the explicitly selected bounded file then associates its artifact', async () => {
    vi.mocked(uploadArtifact).mockResolvedValue({ artifact_id: 'artifact' } as never)
    vi.mocked(importSceneModel).mockResolvedValue({ id: 'model' } as never)
    render(<ScenePanel projectId="p" />)
    await screen.findByRole('option', { name: 'Bench robot' })
    fireEvent.change(screen.getByLabelText('Robot for model'), { target: { value: 'robot' } })
    fireEvent.change(screen.getByLabelText('Local URDF or MJCF'), {
      target: { files: [new File(['<robot name="test"/>'], 'test.urdf')] }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Import model' }))
    await waitFor(() =>
      expect(importSceneModel).toHaveBeenCalledWith(
        'p',
        expect.objectContaining({ robot_id: 'robot', artifact_id: 'artifact', format: 'urdf' }),
        undefined
      )
    )
  })
  it('renders jointless models with an explicit reason', async () => {
    vi.mocked(listSceneModels).mockResolvedValue([
      {
        id: 'model',
        robot_id: 'robot',
        name: 'Fixture CAD',
        version: 1,
        source_current: true,
        bindings: [],
        model: { links: [], joints: [], warnings: [] }
      }
    ] as never)
    render(<ScenePanel projectId="p" />)
    expect(await screen.findByText(/No moving joints/)).toBeInTheDocument()
  })
})

it('uploads only explicitly selected STL assets with reviewed references', async () => {
  vi.mocked(listSceneModels).mockResolvedValue([])
  vi.mocked(uploadArtifact).mockResolvedValue({ artifact_id: 'selected' } as never)
  vi.mocked(importSceneModel).mockResolvedValue({ id: 'model' } as never)
  render(<ScenePanel projectId="p" />)
  await screen.findByRole('option', { name: 'Bench robot' })
  fireEvent.change(screen.getByLabelText('Robot for model'), { target: { value: 'robot' } })
  fireEvent.change(screen.getByLabelText('Local URDF or MJCF'), {
    target: { files: [new File(['<robot/>'], 'robot.urdf')] }
  })
  fireEvent.change(screen.getByLabelText('Local STL assets'), {
    target: { files: [new File(['solid mesh'], 'arm.stl')] }
  })
  fireEvent.change(screen.getByLabelText('Reference for arm.stl'), {
    target: { value: 'package://robot/meshes/arm.stl' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Import model' }))
  await waitFor(() =>
    expect(importSceneModel).toHaveBeenCalledWith(
      'p',
      expect.objectContaining({
        meshes: [{ reference: 'package://robot/meshes/arm.stl', artifact_id: 'selected' }]
      }),
      undefined
    )
  )
})

it('keeps compact scene management in a closed inline disclosure', async () => {
  vi.mocked(listSceneModels).mockResolvedValue([
    {
      id: 'model',
      robot_id: 'robot',
      name: 'Fixture CAD',
      version: 1,
      source_current: true,
      bindings: [],
      model: { links: [], joints: [], warnings: [] }
    }
  ] as never)
  const { container } = render(<ScenePanel projectId="p" compact />)
  await screen.findByText('Fixture CAD')
  const settings = screen.getByText('Scene settings').closest('details')
  expect(settings).not.toHaveAttribute('open')
  expect(settings).toContainElement(screen.getByLabelText('Fixture CAD translation X'))
  expect(container.querySelector('details article')).not.toBeNull()
  expect(screen.getByText('3D scene').closest('details')).toBeNull()
})

it('refuses an import when the account changes across the empty mesh-upload await', async () => {
  vi.mocked(uploadArtifact).mockClear()
  vi.mocked(importSceneModel).mockClear()
  let generation = workspaceSession.workspaceSessionGeneration()
  let uploaded = false
  const generationRead = vi.spyOn(workspaceSession, 'workspaceSessionGeneration')
  generationRead.mockImplementation(() => {
    if (uploaded) {
      uploaded = false
      queueMicrotask(() => {
        generation += 1
      })
    }
    return generation
  })
  vi.mocked(uploadArtifact).mockImplementation(async () => {
    uploaded = true
    return { artifact_id: 'artifact' } as never
  })
  try {
    render(<ScenePanel projectId="p" />)
    await screen.findByRole('option', { name: 'Bench robot' })
    fireEvent.change(screen.getByLabelText('Robot for model'), { target: { value: 'robot' } })
    fireEvent.change(screen.getByLabelText('Local URDF or MJCF'), {
      target: { files: [new File(['<robot/>'], 'robot.urdf')] }
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Import model' }))
    })
    expect(uploadArtifact).toHaveBeenCalledTimes(1)
    expect(importSceneModel).not.toHaveBeenCalled()
  } finally {
    generationRead.mockRestore()
  }
})
