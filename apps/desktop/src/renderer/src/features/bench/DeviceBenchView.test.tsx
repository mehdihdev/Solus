// SOLUSDEV-72 — the device-keyed telemetry view. ONE batched poll per cycle
// for every visible device (per-device 1 Hz polling blew the shared 120/min
// rate budget); panels capped with an honest overflow line. Stream state
// derives from data timestamps — never asserted.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { DeviceBenchView, MAX_DEVICE_PANELS } from './DeviceBenchView'
import * as resources from '../../lib/api/resources'
import type { BenchDeviceRecent } from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getBenchDeviceRecent: vi.fn() }
})

const mockedRecent = vi.mocked(resources.getBenchDeviceRecent)

function entry(deviceId: string): BenchDeviceRecent {
  return {
    device_id: deviceId,
    resolved_entity_id: null,
    signals: [{ signal: 'qvel', points: [{ timestamp: new Date().toISOString(), value: 1.25 }] }]
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedRecent.mockImplementation(async (_p, deviceIds) => deviceIds.map(entry))
})

describe('DeviceBenchView', () => {
  it('polls ONCE for all devices and renders a panel per device', async () => {
    render(<DeviceBenchView projectId="p1" deviceIds={['demo/rod', 'demo/arm']} />)
    expect(await screen.findByText('demo/rod')).toBeInTheDocument()
    expect(screen.getByText('demo/arm')).toBeInTheDocument()
    await waitFor(() =>
      expect(mockedRecent).toHaveBeenCalledWith('p1', ['demo/rod', 'demo/arm'], { limit: 60 })
    )
    // One batched request, not one per device.
    expect(mockedRecent).toHaveBeenCalledTimes(1)
    expect((await screen.findAllByText(/qvel: 1\.25/)).length).toBe(2)
    // Fresh timestamps read as live — derived, not asserted.
    expect(screen.getAllByText('LIVE DATA').length).toBe(2)
  })

  it('caps rendered panels and states the overflow honestly', async () => {
    const many = Array.from({ length: MAX_DEVICE_PANELS + 2 }, (_, i) => `dev/${i}`)
    render(<DeviceBenchView projectId="p1" deviceIds={many} />)
    await waitFor(() =>
      expect(mockedRecent).toHaveBeenCalledWith('p1', many.slice(0, MAX_DEVICE_PANELS), {
        limit: 60
      })
    )
    expect(await screen.findByText('dev/0')).toBeInTheDocument()
    expect(screen.queryByText(`dev/${MAX_DEVICE_PANELS}`)).not.toBeInTheDocument()
    expect(screen.getByText('+2 more devices streaming')).toBeInTheDocument()
  })

  it('says telemetry is unavailable when the poll fails — never fabricates', async () => {
    mockedRecent.mockRejectedValue(new Error('unreachable'))
    render(<DeviceBenchView projectId="p1" deviceIds={['demo/rod']} />)
    expect(await screen.findByText(/Telemetry is unavailable for demo\/rod/)).toBeInTheDocument()
  })

  it('shows an honest empty line for a device with no recent values', async () => {
    mockedRecent.mockResolvedValue([
      { device_id: 'demo/rod', resolved_entity_id: null, signals: [] }
    ])
    render(<DeviceBenchView projectId="p1" deviceIds={['demo/rod']} />)
    expect(await screen.findByText(/No recent values from demo\/rod/)).toBeInTheDocument()
  })
})
