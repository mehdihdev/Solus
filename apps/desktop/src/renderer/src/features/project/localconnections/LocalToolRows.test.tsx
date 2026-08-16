// SOLUSDEV-72 — local tools (bridge) rows: tool name, companion + server state
// merged from bridge status, and the backend's own connect guidance. A bare
// connection never reads as a working tool.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LocalToolRows } from './LocalToolRows'
import type { BridgeStatus, LocalTool } from '../../../lib/api/resources'

const FUSION: LocalTool = {
  type: 'fusion',
  display_name: 'Fusion',
  hosting: 'vendor-run',
  url_host: '127.0.0.1:27182',
  connect_notice: 'Launch Fusion and enable Preferences → General → API → Fusion MCP Server',
  requires: 'companion'
}

describe('LocalToolRows', () => {
  it('says the tool list is unknown when the API is unreachable', () => {
    render(<LocalToolRows tools={null} bridge={null} />)
    expect(screen.getByText(/can't list local tools/i)).toBeInTheDocument()
  })

  it('states plainly when no local tools are registered', () => {
    render(<LocalToolRows tools={[]} bridge={null} />)
    expect(screen.getByText(/no local tools are registered/i)).toBeInTheDocument()
  })

  it('shows the tool with its honest status and the backend guidance', () => {
    const bridge: BridgeStatus = { connected: true, companion_version: '0.1.0', servers: [] }
    render(<LocalToolRows tools={[FUSION]} bridge={bridge} />)
    expect(screen.getByText('Fusion')).toBeInTheDocument()
    expect(screen.getByText('Connected — no tools callable yet')).toBeInTheDocument()
    expect(
      screen.getByText('Launch Fusion and enable Preferences → General → API → Fusion MCP Server')
    ).toBeInTheDocument()
  })

  it('reports the companion offline when the bridge is down', () => {
    render(<LocalToolRows tools={[FUSION]} bridge={null} />)
    expect(screen.getByText('Companion offline')).toBeInTheDocument()
  })
})
