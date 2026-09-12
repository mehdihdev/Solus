// SOLUSDEV-250 P3 — the canvas-edge rail: nothing when no device is pending,
// the compact list for up to three, a "N devices found" pill beyond that.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DetectedDeviceOut } from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import { useDetectedDevicesStore } from './detectedDevicesStore'
import { DevicesFound } from './DevicesFound'
import { PendingDeviceCards } from './PendingDeviceCards'

vi.mock('./DevicesFound', () => ({
  DevicesFound: vi.fn(() => <div data-testid="devices-found" />)
}))

const device = (ref: string): DetectedDeviceOut => ({
  transport: 'usb_serial',
  device_ref: ref,
  identity: null,
  level: 'transport',
  board: null,
  board_class: 'usb_bridge',
  mcu_known: false,
  confidence: 0.4,
  evidence: [],
  ambiguous: false,
  last_seen_path: null
})
const part: Entity = {
  id: 'part',
  type: 'part',
  domain: 'runtime',
  name: 'M1',
  source_key: 'usb_serial:BOUND/1'
}
const onCreated = vi.fn()
function mount(entities: Entity[] = []): ReturnType<typeof render> {
  return render(
    <PendingDeviceCards
      projectId="p1"
      mode="Expert"
      robots={[]}
      entities={entities}
      onCreated={onCreated}
    />
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  useDetectedDevicesStore.getState().reset()
})

describe('PendingDeviceCards', () => {
  it('renders nothing before the store is seeded or when every device is bound', () => {
    expect(mount().container).toBeEmptyDOMElement()
    useDetectedDevicesStore.getState().setDevices([device('usb_serial:BOUND')])
    expect(mount([part]).container).toBeEmptyDOMElement()
  })

  it('renders the compact list for up to three pending devices', () => {
    useDetectedDevicesStore
      .getState()
      .setDevices([device('usb_serial:A'), device('usb_serial:B'), device('usb_serial:C')])
    mount()
    expect(screen.getByTestId('devices-found')).toBeInTheDocument()
    expect(vi.mocked(DevicesFound).mock.calls[0][0]).toMatchObject({
      projectId: 'p1',
      mode: 'Expert',
      compact: true
    })
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('collapses to a pill beyond three and expands on click', async () => {
    useDetectedDevicesStore
      .getState()
      .setDevices(['A', 'B', 'C', 'D'].map((s) => device(`usb_serial:${s}`)))
    mount()
    expect(screen.queryByTestId('devices-found')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '4 devices found' }))
    expect(screen.getByTestId('devices-found')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Hide devices' }))
    expect(screen.queryByTestId('devices-found')).toBeNull()
  })
})
