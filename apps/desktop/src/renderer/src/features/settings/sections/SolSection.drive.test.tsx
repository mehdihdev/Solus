import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SolSection } from './SolSection'
import { useDesktopSol } from '../useDesktopSol'
import { useDriveStatus } from '../useDriveStatus'
import { fakeSolBridge } from '../../sol/solWindow.fixtures'
import { settingsData } from '../settings.fixtures'
import { driveStatus, fakeDriveBridge, type FakeDriveBridge } from '../drive.fixtures'
import type { DriveStatus } from '../../../lib/driveBridge'

const LABEL = 'SOL can use your mouse and keyboard'

function Harness({
  bridge,
  onFixDrive = vi.fn()
}: {
  bridge: FakeDriveBridge | null
  onFixDrive?: () => void
}): React.JSX.Element {
  const sol = useDesktopSol(fakeSolBridge())
  const drive = useDriveStatus(bridge)
  return (
    <SolSection
      data={settingsData()}
      sol={sol}
      drive={drive}
      onFixCapture={vi.fn()}
      onFixDrive={onFixDrive}
    />
  )
}

const renderWith = (status: DriveStatus): FakeDriveBridge => {
  const bridge = fakeDriveBridge(status)
  render(<Harness bridge={bridge} />)
  return bridge
}

describe('SolSection — SOL can use your mouse and keyboard (sol-drive.md §5)', () => {
  it('has no row without the drive bridge', async () => {
    render(<Harness bridge={null} />)
    await screen.findByLabelText('Action mode')
    expect(screen.queryByRole('switch', { name: LABEL })).toBeNull()
  })

  it('is off by default with the plain description', async () => {
    renderWith(driveStatus())
    const toggle = await screen.findByRole('switch', { name: LABEL })
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    expect(toggle).toBeEnabled()
    expect(
      screen.getByText(
        'When on, SOL can click and type in KiCad for a step you approve. Moving the mouse or pressing Esc stops it.'
      )
    ).toBeInTheDocument()
  })

  it('turns driving on through the bridge', async () => {
    const bridge = renderWith(driveStatus())
    await userEvent.click(await screen.findByRole('switch', { name: LABEL }))
    expect(bridge.setDrive).toHaveBeenCalledWith(true)
    await waitFor(() =>
      expect(screen.getByRole('switch', { name: LABEL })).toHaveAttribute('aria-checked', 'true')
    )
  })

  it.each([
    ['not_macos', 'Only on macOS for now.'],
    ['no_helper', 'The input helper is missing from this install.'],
    ['no_folder', 'Link this project to a folder on this computer first.'],
    [
      'nested_folder',
      "This project's folder is inside, or contains, another linked project's folder. Move one of them so SOL can't act on the other project's files."
    ]
  ] as const)('when unavailable (%s), disables the switch and says why', async (reason, copy) => {
    renderWith(driveStatus({ available: false, reason, trust: null }))
    expect(await screen.findByRole('switch', { name: LABEL })).toBeDisabled()
    expect(screen.getByText(copy)).toBeInTheDocument()
  })

  it('tags a missing grant and sends the fix to Needs attention', async () => {
    const onFixDrive = vi.fn()
    const bridge = fakeDriveBridge(
      driveStatus({ enabled: true, trust: { accessibility: false, screenRecording: true } })
    )
    render(<Harness bridge={bridge} onFixDrive={onFixDrive} />)
    await screen.findByRole('switch', { name: LABEL })
    expect(screen.getByText('Permission needed')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'How to fix' }))
    expect(onFixDrive).toHaveBeenCalled()
  })

  it('has no tag when every grant is in place', async () => {
    renderWith(driveStatus({ enabled: true }))
    await screen.findByRole('switch', { name: LABEL })
    expect(screen.queryByText('Permission needed')).toBeNull()
  })

  it('marks a development build of the helper', async () => {
    renderWith(driveStatus({ unsignedDev: true }))
    await screen.findByRole('switch', { name: LABEL })
    expect(screen.getByText('Development build')).toBeInTheDocument()
  })

  it('shows a refused change inline', async () => {
    const bridge = fakeDriveBridge(driveStatus())
    vi.mocked(bridge.setDrive).mockResolvedValueOnce(null)
    render(<Harness bridge={bridge} />)
    await userEvent.click(await screen.findByRole('switch', { name: LABEL }))
    expect(
      await screen.findByText("The desktop app didn't accept that change.")
    ).toBeInTheDocument()
  })
})
