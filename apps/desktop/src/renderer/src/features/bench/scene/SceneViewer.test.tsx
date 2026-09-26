import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SceneViewer } from './SceneViewer'

vi.mock('three', async (original) => {
  const actual = await original<typeof import('three')>()
  return {
    ...actual,
    WebGLRenderer: vi.fn(() => {
      throw new Error('No GPU')
    })
  }
})
describe('scene viewer availability', () => {
  it('explains missing graphics without claiming the model failed to import', async () => {
    render(<SceneViewer models={[]} poses={{}} values={{}} />)
    expect((await screen.findByRole('status')).textContent).toMatch(/3D rendering is unavailable/)
  })
})
