// The topbar bridge pill (SOLUSDEV-154 / BRG-03): dot + label per pill state,
// with a click popover listing each vendored MCP server. The hook is mocked —
// polling behavior is covered in useBridgeStatus.test.ts.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BridgePill } from './BridgePill'
import { useBridgeStatus } from './useBridgeStatus'
import type { BridgeStatus } from '../../lib/api/resources'

vi.mock('./useBridgeStatus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./useBridgeStatus')>()
  return { ...actual, useBridgeStatus: vi.fn() }
})

const READY: BridgeStatus = {
  connected: true,
  companion_version: '0.1.0',
  servers: [{ name: 'github', state: 'ready', detail: null, updated_at: '2026-07-23T00:00:00Z' }]
}

beforeEach(() => {
  vi.mocked(useBridgeStatus).mockReturnValue(null)
})

describe('BridgePill', () => {
  it('shows "Bridge offline" when the companion is not connected', () => {
    render(<BridgePill projectId="p1" />)
    expect(screen.getByText('Bridge offline')).toBeInTheDocument()
  })

  it('shows "Bridge" when connected and all servers are healthy', () => {
    vi.mocked(useBridgeStatus).mockReturnValue(READY)
    render(<BridgePill projectId="p1" />)
    expect(screen.getByText('Bridge')).toBeInTheDocument()
  })

  it('shows "Bridge busy" when any server is busy', () => {
    vi.mocked(useBridgeStatus).mockReturnValue({
      ...READY,
      servers: [
        { name: 'github', state: 'busy', detail: 'sync running', updated_at: '' },
        { name: 'kicad', state: 'ready', detail: null, updated_at: '' }
      ]
    })
    render(<BridgePill projectId="p1" />)
    expect(screen.getByText('Bridge busy')).toBeInTheDocument()
  })

  it('shows "Bridge attention" when a server errored', () => {
    vi.mocked(useBridgeStatus).mockReturnValue({
      ...READY,
      servers: [{ name: 'kicad', state: 'error', detail: 'crashed', updated_at: '' }]
    })
    render(<BridgePill projectId="p1" />)
    expect(screen.getByText('Bridge attention')).toBeInTheDocument()
  })

  it('opens a popover listing each server with state and detail', async () => {
    vi.mocked(useBridgeStatus).mockReturnValue({
      ...READY,
      servers: [
        { name: 'github', state: 'ready', detail: null, updated_at: '' },
        { name: 'kicad', state: 'error', detail: 'exited with code 1', updated_at: '' }
      ]
    })
    render(<BridgePill projectId="p1" />)
    await userEvent.click(screen.getByTestId('bridge-pill'))
    expect(screen.getByText('github')).toBeInTheDocument()
    expect(screen.getByText('kicad')).toBeInTheDocument()
    expect(screen.getByText(/exited with code 1/)).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('bridge-pill'))
    expect(screen.queryByText('github')).not.toBeInTheDocument()
  })

  it('explains honestly in the popover when the companion is offline', async () => {
    render(<BridgePill projectId="p1" />)
    await userEvent.click(screen.getByTestId('bridge-pill'))
    expect(screen.getByText(/companion isn't connected/i)).toBeInTheDocument()
  })
})
