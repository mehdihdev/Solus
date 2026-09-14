import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { SimulationModelSetup } from './SimulationModelSetup'
import { api } from '../../lib/api/client'
vi.mock('../../lib/api/client', () => ({ api: { request: vi.fn() } }))
beforeEach(() => {
  vi.mocked(api.request).mockReset()
})
describe('simulation model setup', () => {
  it('discloses the template then creates the graph through the bounded route', async () => {
    vi.mocked(api.request).mockResolvedValue({ model: { id: 'model-1' }, created: true })
    render(<SimulationModelSetup projectId="p1" />)
    expect(screen.getByText(/eight links, six joints/i)).toBeTruthy()
    expect(api.request).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Add SO-101 model' }))
    await waitFor(() => expect(screen.getByText(/model-1/)).toBeTruthy())
    expect(api.request).toHaveBeenCalledWith('/projects/p1/simulation-models', {
      method: 'POST',
      body: { template: 'so101_new_calib_v1' }
    })
    expect(api.request).toHaveBeenCalledTimes(1)
  })
  it('discards an old project result and prevents duplicate pending requests', async () => {
    let finish!: (v: unknown) => void
    vi.mocked(api.request).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve
      })
    )
    const view = render(<SimulationModelSetup projectId="p1" />)
    fireEvent.click(screen.getByRole('button', { name: 'Add SO-101 model' }))
    fireEvent.click(screen.getByRole('button', { name: 'Adding model…' }))
    expect(api.request).toHaveBeenCalledTimes(1)
    view.rerender(<SimulationModelSetup projectId="p2" />)
    finish({ model: { id: 'old-model' }, created: true })
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Add SO-101 model' })).toBeTruthy()
    )
    expect(screen.queryByText(/old-model/)).toBeNull()
  })
  it('reports failure without claiming the model was created', async () => {
    vi.mocked(api.request).mockRejectedValue(new Error('Permission denied'))
    render(<SimulationModelSetup projectId="p1" />)
    fireEvent.click(screen.getByRole('button', { name: 'Add SO-101 model' }))
    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toContain('Permission denied')
    )
  })
})
