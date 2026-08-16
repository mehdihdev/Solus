// SOLUSDEV-72 — the Local Connections section on the Sources screen: three
// subsections (simulators, devices, local tools) rendered from live data with
// honest offline/unavailable states. runner.available=false means livebench
// is not installed server-side — every simulator/device control is disabled
// with that reason.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { LocalConnectionsSection } from './LocalConnectionsSection'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import * as resources from '../../../lib/api/resources'
import type { BenchSession, BenchSources } from '../../../lib/api/resources'

vi.mock('../../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../lib/api/resources')>()
  return {
    ...actual,
    getBenchSources: vi.fn(),
    listBenchSessions: vi.fn(),
    createBenchSession: vi.fn(),
    stopBenchSession: vi.fn(),
    listLocalTools: vi.fn(),
    getBridgeStatus: vi.fn()
  }
})

const SOURCES: BenchSources = {
  runner: { available: true, reason: null },
  simulators: [
    { kind: 'mujoco', available: true, reason: null },
    { kind: 'gazebo', available: false, reason: 'gz CLI not on PATH' }
  ],
  devices: [
    {
      device_path: '/dev/ttyACM0',
      by_id_path: null,
      serial_number: '5B42135040',
      vid: '1a86',
      pid: '55d3',
      board: 'Arduino Uno R3',
      board_class: 'arduino',
      mcu_known: true,
      confidence: 0.9,
      ambiguous: false,
      note: null
    }
  ]
}

const MUJOCO_SESSION: BenchSession = {
  id: 's1',
  mode: 'sim',
  provider: 'mujoco',
  status: 'active',
  link: 'streaming',
  label: 'MuJoCo demo scene',
  created_at: '2026-08-16T00:00:00Z',
  ended_at: null,
  device: null,
  device_ids: ['demo/rod'],
  counts: { ingested: 12, unresolved: 0 },
  last_summary: null
}

const mockedSources = vi.mocked(resources.getBenchSources)
const mockedSessions = vi.mocked(resources.listBenchSessions)
const mockedCreate = vi.mocked(resources.createBenchSession)
const mockedStop = vi.mocked(resources.stopBenchSession)
const mockedTools = vi.mocked(resources.listLocalTools)
const mockedBridge = vi.mocked(resources.getBridgeStatus)

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ linked: true })
  mockedSources.mockResolvedValue(SOURCES)
  mockedSessions.mockResolvedValue([])
  mockedCreate.mockResolvedValue(MUJOCO_SESSION)
  mockedStop.mockResolvedValue({ ...MUJOCO_SESSION, status: 'ended' })
  mockedTools.mockResolvedValue([])
  mockedBridge.mockRejectedValue(new Error('offline'))
})

describe('LocalConnectionsSection', () => {
  it('renders the three subsections from live data', async () => {
    render(<LocalConnectionsSection projectId="p1" />)
    expect(await screen.findByText('SIMULATORS')).toBeInTheDocument()
    expect(screen.getByText('DEVICES')).toBeInTheDocument()
    expect(screen.getByText('LOCAL TOOLS (BRIDGE)')).toBeInTheDocument()
    expect(await screen.findByText('MuJoCo')).toBeInTheDocument()
    expect(screen.getByText('Arduino Uno R3')).toBeInTheDocument()
  })

  it('says so honestly when the bench sources are unreachable', async () => {
    mockedSources.mockRejectedValue(new Error('unreachable'))
    render(<LocalConnectionsSection projectId="p1" />)
    expect(await screen.findByText(/can't reach its API/i)).toBeInTheDocument()
  })

  it('an unavailable simulator states its reason and is unstartable', async () => {
    render(<LocalConnectionsSection projectId="p1" />)
    expect(await screen.findByText('gz CLI not on PATH')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start Gazebo' })).toBeDisabled()
  })

  it('runner unavailable disables EVERY simulator and device control with the reason', async () => {
    mockedSources.mockResolvedValue({
      ...SOURCES,
      runner: { available: false, reason: 'livebench is not installed' }
    })
    render(<LocalConnectionsSection projectId="p1" />)
    expect((await screen.findAllByText('livebench is not installed')).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Start MuJoCo demo scene' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Connect /dev/ttyACM0' })).toBeDisabled()
  })

  it('starts the MuJoCo demo scene and refreshes the session list', async () => {
    render(<LocalConnectionsSection projectId="p1" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Start MuJoCo demo scene' }))
    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith('p1', {
        mode: 'sim',
        config: { provider: 'mujoco' }
      })
    )
    await waitFor(() => expect(mockedSources.mock.calls.length).toBeGreaterThan(1))
  })

  it('shows an active session inline with a working stop button', async () => {
    mockedSessions.mockResolvedValue([MUJOCO_SESSION])
    render(<LocalConnectionsSection projectId="p1" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Stop MuJoCo demo scene' }))
    await waitFor(() => expect(mockedStop).toHaveBeenCalledWith('p1', 's1'))
  })

  it('connects a serial device through the real session route', async () => {
    render(<LocalConnectionsSection projectId="p1" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Connect /dev/ttyACM0' }))
    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith('p1', {
        mode: 'real',
        config: { provider: 'serial', serial_number: '5B42135040' }
      })
    )
  })

  it('lists local tools with honest bridge status', async () => {
    mockedTools.mockResolvedValue([
      {
        type: 'fusion',
        display_name: 'Fusion',
        hosting: 'vendor-run',
        url_host: '127.0.0.1:27182',
        connect_notice: 'Launch Fusion and enable the MCP server',
        requires: 'companion'
      }
    ])
    render(<LocalConnectionsSection projectId="p1" />)
    expect(await screen.findByText('Fusion')).toBeInTheDocument()
    expect(screen.getByText('Companion offline')).toBeInTheDocument()
    expect(screen.getByText('Launch Fusion and enable the MCP server')).toBeInTheDocument()
  })

  it('keeps an orphaned session (device gone) visible and stoppable', async () => {
    const orphan: BenchSession = {
      ...MUJOCO_SESSION,
      id: 'orphan',
      mode: 'real',
      provider: 'serial',
      label: 'Serial /dev/ttyUSB9',
      // The REAL session.device echo: 3 fields, never a full BenchDevice.
      device: { serial_number: 'GONE', device_path: '/dev/ttyUSB9', baud: 115200 }
    }
    mockedSessions.mockResolvedValue([orphan])
    render(<LocalConnectionsSection projectId="p1" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Stop Serial /dev/ttyUSB9' }))
    await waitFor(() => expect(mockedStop).toHaveBeenCalledWith('p1', 'orphan'))
  })
})
