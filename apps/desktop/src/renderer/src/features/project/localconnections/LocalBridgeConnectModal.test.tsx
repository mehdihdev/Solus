// SOLUSDEV-72 — the connect action for a local-bridge tile: not an OAuth flow,
// but honest companion + launch guidance straight from the registry entry.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { LocalBridgeConnectModal } from './LocalBridgeConnectModal'
import type { LocalTool } from '../../../lib/api/resources'

const FUSION: LocalTool = {
  type: 'fusion',
  display_name: 'Fusion',
  hosting: 'vendor-run',
  url_host: '127.0.0.1:27182',
  connect_notice: 'Launch Fusion and enable Preferences → General → API → Fusion MCP Server',
  requires: 'companion'
}

describe('LocalBridgeConnectModal', () => {
  it('shows the tool name, the companion requirement, and the backend guidance', () => {
    render(<LocalBridgeConnectModal tool={FUSION} onClose={vi.fn()} />)
    expect(screen.getByText('Connect Fusion')).toBeInTheDocument()
    expect(
      screen.getByText('Launch Fusion and enable Preferences → General → API → Fusion MCP Server')
    ).toBeInTheDocument()
    expect(screen.getByText(/Solus companion/i)).toBeInTheDocument()
    expect(screen.getByText(/127\.0\.0\.1:27182/)).toBeInTheDocument()
  })

  it('closes', () => {
    const onClose = vi.fn()
    render(<LocalBridgeConnectModal tool={FUSION} onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: 'Got it' }))
    expect(onClose).toHaveBeenCalled()
  })
})
