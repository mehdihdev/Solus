import { fireEvent, render, screen, act } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { HostMirrorOffer } from './HostMirrorOffer'
import { sendMessage } from '../../sol/solChatStore'
vi.mock('../../sol/solChatStore', () => ({ sendMessage: vi.fn() }))
vi.mock('../../../lib/desktopBridge', () => ({ getDesktopSolBridge: () => ({ open: vi.fn() }) }))
vi.mock('../workspaceSession', () => ({ workspaceSessionGeneration: () => 1 }))
const props = { projectId: 'p', sourceId: 's', robotId: 'r', generation: 1, files: ['control.py'] }
beforeEach(() => {
  vi.mocked(sendMessage).mockReset()
})
function fill(): void {
  fireEvent.change(screen.getByLabelText('Control loop file'), { target: { value: 'control.py' } })
  fireEvent.change(screen.getByLabelText('Control object'), { target: { value: 'robot' } })
  fireEvent.change(screen.getByLabelText('Insert after this exact line'), {
    target: { value: 'robot.connect()' }
  })
  fireEvent.change(screen.getByLabelText('Method to observe'), {
    target: { value: 'get_observation' }
  })
  fireEvent.change(screen.getByLabelText('Signal mappings'), {
    target: { value: 'a.position=a|deg' }
  })
  fireEvent.change(screen.getByLabelText('Device ID'), { target: { value: 'host:arm' } })
  fireEvent.change(screen.getByLabelText('Loopback UDP port'), { target: { value: '9876' } })
}
it('requires explicit choices and a snippet preview before requesting the central diff gate', async () => {
  vi.mocked(sendMessage).mockResolvedValue(true)
  render(<HostMirrorOffer {...props} />)
  expect(sendMessage).not.toHaveBeenCalled()
  fill()
  fireEvent.click(screen.getByRole('button', { name: 'Preview mirror shim' }))
  expect(screen.getByLabelText('Proposed mirror shim').textContent).toContain('solus.MirrorConfig')
  expect(sendMessage).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Request file diff review' }))
  await screen.findByText(/Review requested in SOL/)
  expect(sendMessage).toHaveBeenCalledOnce()
  expect(vi.mocked(sendMessage).mock.calls[0]?.[2]).toBe('do')
  expect(vi.mocked(sendMessage).mock.calls[0]?.[6]).toEqual({ forceConfirmation: true })
  expect(screen.queryByText(/installed successfully/i)).toBeNull()
})
it('invalidates a preview when choices change and refuses an invalid file', () => {
  render(<HostMirrorOffer {...props} />)
  fill()
  fireEvent.click(screen.getByRole('button', { name: 'Preview mirror shim' }))
  fireEvent.change(screen.getByLabelText('Control loop file'), { target: { value: '../other.py' } })
  expect(screen.queryByRole('button', { name: 'Request file diff review' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Preview mirror shim' }))
  expect(screen.getByRole('alert')).toBeTruthy()
  expect(sendMessage).not.toHaveBeenCalled()
})
it('drops async completion after unmount and reports unverified requests honestly', async () => {
  let resolve!: (value: boolean) => void
  vi.mocked(sendMessage).mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done
      })
  )
  const view = render(<HostMirrorOffer {...props} />)
  fill()
  fireEvent.click(screen.getByRole('button', { name: 'Preview mirror shim' }))
  fireEvent.click(screen.getByRole('button', { name: 'Request file diff review' }))
  view.unmount()
  await act(async () => resolve(false))
  expect(sendMessage).toHaveBeenCalledOnce()
})

it('reports a rejected review request without claiming installation or auto retrying', async () => {
  vi.mocked(sendMessage).mockResolvedValue(false)
  render(<HostMirrorOffer {...props} />)
  fill()
  fireEvent.click(screen.getByRole('button', { name: 'Preview mirror shim' }))
  fireEvent.click(screen.getByRole('button', { name: 'Request file diff review' }))
  await screen.findByRole('alert')
  expect(screen.getByRole('button', { name: 'Request file diff review' })).toBeDisabled()
  expect(sendMessage).toHaveBeenCalledOnce()
})
it('invalidates a pending offer when project/source identity changes', () => {
  const view = render(<HostMirrorOffer {...props} />)
  fill()
  fireEvent.click(screen.getByRole('button', { name: 'Preview mirror shim' }))
  view.rerender(<HostMirrorOffer {...props} sourceId="different" />)
  expect(screen.queryByRole('button', { name: 'Request file diff review' })).toBeNull()
  expect(screen.getByLabelText('Control loop file')).toHaveValue('')
  expect(sendMessage).not.toHaveBeenCalled()
})

it('rejects an oversized review locally without sending a truncated request', () => {
  render(<HostMirrorOffer {...props} />)
  fill()
  fireEvent.change(screen.getByLabelText('Signal mappings'), {
    target: {
      value: Array.from({ length: 256 }, (_, index) => `s${index}=${'x'.repeat(128)}`).join('\n')
    }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Preview mirror shim' }))
  expect(screen.getByRole('alert')).toHaveTextContent(/reduce.*mappings/i)
  expect(screen.queryByRole('button', { name: 'Request file diff review' })).toBeNull()
  expect(sendMessage).not.toHaveBeenCalled()
})
