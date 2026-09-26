import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { FirmwareTelemetryOffer } from './FirmwareTelemetryOffer'
import { sendMessage } from '../../sol/solChatStore'
import { useLocalFolder, type LocalFolderController } from '../../project/useLocalFolder'
vi.mock('../../sol/solChatStore', () => ({ sendMessage: vi.fn() }))
vi.mock('../../project/useLocalFolder', () => ({ useLocalFolder: vi.fn() }))
vi.mock('../../project/ProjectFolderCard', () => ({
  ProjectFolderCard: () => <div>Local folder picker</div>
}))
vi.mock('../../../lib/desktopBridge', () => ({
  getDesktopSolBridge: () => ({ open: vi.fn() }),
  getDesktopFolderBridge: () => null
}))
const source = '00000000-0000-0000-0000-000000000001'
const local = {
  status: 'ready',
  machineAvailable: true,
  link: vi.fn(async () => {}),
  unlink: vi.fn(async () => {}),
  open: vi.fn(async () => null),
  refresh: vi.fn(async () => {}),
  view: {
    source: {
      id: source,
      project_id: 'p',
      type: 'local',
      status: 'connected',
      name: 'Selected local',
      config: {},
      account_login: null,
      last_synced_at: null,
      last_error: null,
      created_at: '2026-09-14T00:00:00Z',
      updated_at: '2026-09-14T00:00:00Z'
    },
    bridge: { connected: true, tools_installed: {} },
    detected: [
      {
        entity_id: 'sketch',
        entity_key: 'arduino:main.ino',
        tool: 'arduino',
        path: 'main.ino',
        name: 'Sketch',
        open_targets: []
      },
      {
        entity_id: 'python',
        entity_key: 'python:control.py',
        tool: 'python',
        path: 'control.py',
        name: 'Control',
        open_targets: []
      }
    ]
  }
} satisfies LocalFolderController
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(useLocalFolder).mockReturnValue(local)
  vi.mocked(sendMessage).mockResolvedValue(true)
})
function fill(): void {
  fireEvent.change(screen.getByLabelText('Firmware local source'), { target: { value: source } })
  fireEvent.change(screen.getByLabelText('Existing sketch'), { target: { value: 'main.ino' } })
  fireEvent.change(screen.getByLabelText('Firmware device ID'), { target: { value: 'usb:board' } })
  fireEvent.change(screen.getByLabelText('Existing serial baud'), { target: { value: '115200' } })
  fireEvent.change(screen.getByLabelText('Publish after exact line'), {
    target: { value: 'value = readValue();' }
  })
  fireEvent.change(screen.getByLabelText('Numeric signal mappings'), {
    target: { value: 'value=value|raw' }
  })
}
it('offers exact manifest file and full snippet before forced central diff review', async () => {
  render(<FirmwareTelemetryOffer projectId="p" />)
  fill()
  expect(screen.queryByText('control.py')).not.toBeInTheDocument()
  fireEvent.click(screen.getByText('Preview telemetry additions'))
  expect(screen.getByLabelText('Proposed loop additions')).toHaveTextContent(
    'static_cast<float>(value)'
  )
  expect(sendMessage).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('Request firmware file diff'))
  await screen.findByText(/File review requested/)
  expect(sendMessage).toHaveBeenCalledWith(
    'p',
    expect.stringContaining('main.ino'),
    'do',
    [],
    false,
    undefined,
    { forceConfirmation: true }
  )
  expect(screen.getByText('Request firmware file diff')).toBeDisabled()
})
it('exposes unavailable local capability honestly', () => {
  vi.mocked(useLocalFolder).mockReturnValue({
    ...local,
    status: 'unavailable',
    view: null
  } as unknown as ReturnType<typeof useLocalFolder>)
  render(<FirmwareTelemetryOffer projectId="p" />)
  expect(screen.getByText(/Connect and synchronize/)).toBeVisible()
  expect(screen.queryByText('Preview telemetry additions')).not.toBeInTheDocument()
})
it('drops stale source scope while a request is pending', async () => {
  let done!: (v: boolean) => void
  vi.mocked(sendMessage).mockReturnValue(
    new Promise((r) => {
      done = r
    })
  )
  const view = render(<FirmwareTelemetryOffer projectId="p" />)
  fill()
  fireEvent.click(screen.getByText('Preview telemetry additions'))
  fireEvent.click(screen.getByText('Request firmware file diff'))
  view.rerender(<FirmwareTelemetryOffer projectId="q" />)
  await act(async () => done(true))
  expect(screen.queryByText(/File review requested/)).not.toBeInTheDocument()
})
it('locks uncertain request and does not claim installed firmware', async () => {
  vi.mocked(sendMessage).mockResolvedValue(false)
  render(<FirmwareTelemetryOffer projectId="p" />)
  fill()
  fireEvent.click(screen.getByText('Preview telemetry additions'))
  fireEvent.click(screen.getByText('Request firmware file diff'))
  await screen.findByRole('alert')
  expect(screen.getByText('Request firmware file diff')).toBeDisabled()
  expect(screen.queryByText(/File review requested/)).not.toBeInTheDocument()
})
it('invalidates preview when manifest or source identity changes', () => {
  const view = render(<FirmwareTelemetryOffer projectId="p" />)
  fill()
  fireEvent.click(screen.getByText('Preview telemetry additions'))
  expect(screen.getByText('Request firmware file diff')).toBeVisible()
  vi.mocked(useLocalFolder).mockReturnValue({
    ...local,
    view: { ...local.view, detected: [{ ...local.view.detected[0], path: 'other.ino' }] }
  })
  view.rerender(<FirmwareTelemetryOffer projectId="p" />)
  expect(screen.queryByText('Request firmware file diff')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Firmware local source')).toHaveValue('')
})
it('requires explicit source selection and reports invalid declarations before any request', () => {
  render(<FirmwareTelemetryOffer projectId="p" />)
  expect(screen.queryByText('Preview telemetry additions')).not.toBeInTheDocument()
  fill()
  fireEvent.change(screen.getByLabelText('Numeric signal mappings'), {
    target: { value: 'x=analogRead(A0)' }
  })
  fireEvent.click(screen.getByText('Preview telemetry additions'))
  expect(screen.getByRole('alert')).toHaveTextContent('Expressions and function calls')
  expect(sendMessage).not.toHaveBeenCalled()
})
it('does not make a remote source eligible and reports a missing sketch manifest', () => {
  vi.mocked(useLocalFolder).mockReturnValue({
    ...local,
    view: { ...local.view, source: { ...local.view.source, type: 'github' } }
  })
  const view = render(<FirmwareTelemetryOffer projectId="p" />)
  expect(screen.queryByLabelText('Firmware local source')).not.toBeInTheDocument()
  vi.mocked(useLocalFolder).mockReturnValue({
    ...local,
    view: { ...local.view, detected: [] }
  })
  view.rerender(<FirmwareTelemetryOffer projectId="p" />)
  fireEvent.change(screen.getByLabelText('Firmware local source'), { target: { value: source } })
  expect(screen.getByText(/No .ino files/)).toBeVisible()
})
