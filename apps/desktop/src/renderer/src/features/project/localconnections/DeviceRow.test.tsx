// SOLUSDEV-72 — device row honesty: render exactly what the backend claims
// (usb_bridge ⇒ "MCU unknown", confidence shown), always show the identity
// discriminator (serial or its absence), require an explicit user pick for
// ambiguous/serial-less devices, and persist user labels by serial number.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { DeviceRow } from './DeviceRow'
import { useDeviceLabelStore, DEVICE_LABELS_STORAGE_KEY } from './deviceLabelStore'
import type { BenchDevice, BenchSession } from '../../../lib/api/resources'

function device(overrides: Partial<BenchDevice> = {}): BenchDevice {
  return {
    device_path: '/dev/ttyACM0',
    by_id_path: '/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B42135040-if00',
    serial_number: '5B42135040',
    vid: '1a86',
    pid: '55d3',
    board: 'WCH CH343/CH9102 USB-serial bridge',
    board_class: 'usb_bridge',
    mcu_known: false,
    confidence: 0.3,
    ambiguous: false,
    note: null,
    ...overrides
  }
}

const REAL_SESSION: BenchSession = {
  id: 'r1',
  mode: 'real',
  provider: 'serial',
  status: 'active',
  link: 'streaming',
  label: 'Serial /dev/ttyACM0',
  created_at: '2026-08-16T00:00:00Z',
  ended_at: null,
  // The REAL session.device echo: 3 fields, never a full BenchDevice.
  device: { serial_number: '5B42135040', device_path: null, baud: 115200 },
  device_ids: [],
  counts: { ingested: 5, unresolved: 0 },
  last_summary: null
}

function renderRow(
  d: BenchDevice,
  overrides: Partial<React.ComponentProps<typeof DeviceRow>> = {}
): { onConnect: ReturnType<typeof vi.fn>; onStop: ReturnType<typeof vi.fn> } {
  const onConnect = vi.fn(async () => null)
  const onStop = vi.fn()
  render(
    <DeviceRow
      device={d}
      sessions={[]}
      disabledReason={null}
      onConnect={onConnect}
      onStop={onStop}
      {...overrides}
    />
  )
  return { onConnect, onStop }
}

beforeEach(() => {
  useDeviceLabelStore.setState({ labels: {} })
  localStorage.removeItem(DEVICE_LABELS_STORAGE_KEY)
})

describe('DeviceRow — honesty', () => {
  it('a usb_bridge device reads "USB-serial bridge — MCU unknown", never a guessed board', () => {
    renderRow(device())
    expect(screen.getByText('USB-serial bridge — MCU unknown')).toBeInTheDocument()
    expect(screen.getByText(/CONFIDENCE 0\.3/)).toBeInTheDocument()
  })

  it('shows the serial number as the identity discriminator', () => {
    renderRow(device())
    expect(screen.getByText('5B42135040')).toBeInTheDocument()
  })

  it('badges a serial-less device as NO SERIAL', () => {
    renderRow(device({ serial_number: null }))
    expect(screen.getByText('NO SERIAL')).toBeInTheDocument()
  })
})

describe('DeviceRow — connect', () => {
  it('connects an unambiguous serial device by serial number only', async () => {
    const { onConnect } = renderRow(device())
    fireEvent.click(screen.getByRole('button', { name: 'Connect /dev/ttyACM0' }))
    await waitFor(() =>
      expect(onConnect).toHaveBeenCalledWith({ provider: 'serial', serial_number: '5B42135040' })
    )
  })

  it('an ambiguous device requires an explicit pick of the device path first', async () => {
    const { onConnect } = renderRow(device({ ambiguous: true, note: 'shares serial with ttyACM1' }))
    // The discriminator is shown: path + note. Connect is disabled until picked.
    expect(screen.getByText(/shares serial with ttyACM1/)).toBeInTheDocument()
    const connect = screen.getByRole('button', { name: 'Connect /dev/ttyACM0' })
    expect(connect).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Use /dev/ttyACM0' }))
    fireEvent.click(connect)
    await waitFor(() =>
      expect(onConnect).toHaveBeenCalledWith({
        provider: 'serial',
        serial_number: '5B42135040',
        confirmed_device_path: '/dev/ttyACM0'
      })
    )
  })

  it('a serial-less device also requires the explicit pick and sends the confirmed path', async () => {
    const { onConnect } = renderRow(device({ serial_number: null }))
    const connect = screen.getByRole('button', { name: 'Connect /dev/ttyACM0' })
    expect(connect).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Use /dev/ttyACM0' }))
    fireEvent.click(connect)
    await waitFor(() =>
      expect(onConnect).toHaveBeenCalledWith({
        provider: 'serial',
        confirmed_device_path: '/dev/ttyACM0'
      })
    )
  })

  it('is unconnectable with the stated reason when the runner is unavailable', () => {
    renderRow(device(), { disabledReason: 'livebench is not installed' })
    expect(screen.getByRole('button', { name: 'Connect /dev/ttyACM0' })).toBeDisabled()
    expect(screen.getByText(/livebench is not installed/)).toBeInTheDocument()
  })

  it('surfaces the connect failure text from the handler', async () => {
    const onConnect = vi.fn(async () => 'Session limit reached — stop an active session first.')
    render(
      <DeviceRow
        device={device()}
        sessions={[]}
        disabledReason={null}
        onConnect={onConnect}
        onStop={vi.fn()}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Connect /dev/ttyACM0' }))
    expect(
      await screen.findByText('Session limit reached — stop an active session first.')
    ).toBeInTheDocument()
  })
})

describe('DeviceRow — labels', () => {
  it('persists a user label keyed by serial number', () => {
    renderRow(device())
    fireEvent.change(screen.getByRole('textbox', { name: 'Label for /dev/ttyACM0' }), {
      target: { value: 'leader' }
    })
    expect(useDeviceLabelStore.getState().labels['5B42135040']).toBe('leader')
  })

  it('marks a path-keyed label (no serial) as unverified after replug', () => {
    renderRow(device({ serial_number: null }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Label for /dev/ttyACM0' }), {
      target: { value: 'follower' }
    })
    expect(useDeviceLabelStore.getState().labels['1a86:55d3:/dev/ttyACM0']).toBe('follower')
    expect(screen.getByText(/unverified after replug/i)).toBeInTheDocument()
  })
})

describe('DeviceRow — sessions', () => {
  it('shows the active session inline with a stop control', () => {
    const { onStop } = renderRow(device(), { sessions: [REAL_SESSION] })
    fireEvent.click(screen.getByRole('button', { name: 'Stop Serial /dev/ttyACM0' }))
    expect(onStop).toHaveBeenCalledWith('r1')
  })
})
