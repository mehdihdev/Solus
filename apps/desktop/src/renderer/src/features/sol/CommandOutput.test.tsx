import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CommandOutput } from './CommandOutput'
import { api } from '../../lib/api/client'

vi.mock('../../lib/api/client', () => ({ api: { request: vi.fn() } }))

describe('command progress', () => {
  it('shows escaped incremental output while the command is still running', async () => {
    vi.mocked(api.request).mockResolvedValue({
      chunks: [{ sequence: 1, stream: 'stdout', text: '<script>progress</script>' }],
      cursor: 1,
      complete: false,
      truncated: false
    })
    const view = render(<CommandOutput projectId="p" confirmationId="c" />)
    await waitFor(() => expect(screen.getByText('<script>progress</script>')).toBeTruthy())
    expect(view.container.querySelector('script')).toBeNull()
    expect(api.request).toHaveBeenCalledWith('/projects/p/sol/confirmations/c/output?cursor=0')
    view.unmount()
  })
  it('reports unavailable progress without implying command failure or retry', async () => {
    vi.mocked(api.request).mockRejectedValue(new Error('offline'))
    const view = render(<CommandOutput projectId="p" confirmationId="c" />)
    await waitFor(() => expect(screen.getByText(/Progress unavailable/)).toBeTruthy())
    view.unmount()
  })
})
