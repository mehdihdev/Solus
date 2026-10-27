import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DriveStrip } from './DriveStrip'
import { newCommandRun, type CommandRun } from './commandRuns'
import { fakeDriveBridge } from '../settings/drive.fixtures'

const running = (text = ''): CommandRun => ({ ...newCommandRun('cf1', 'drive.step'), text })

describe('DriveStrip (sol-drive.md §5 While a step runs)', () => {
  it('says it is starting before the first progress line and tells main a step runs', () => {
    const bridge = fakeDriveBridge()
    render(<DriveStrip run={running()} bridge={bridge} />)
    expect(screen.getByText('DRIVING KICAD · STARTING')).toBeInTheDocument()
    expect(bridge.setDriving).toHaveBeenCalledWith(true)
    expect(bridge.setDriving).toHaveBeenCalledTimes(1)
  })

  it('shows step k of N and a progress bar from the latest line', () => {
    const bridge = fakeDriveBridge()
    const { rerender } = render(
      <DriveStrip run={running('action 1/15 · click · 1.0 s\n')} bridge={bridge} />
    )
    rerender(
      <DriveStrip
        run={running('action 1/15 · click · 1.0 s\naction 3/15 · type · 4.2 s\n')}
        bridge={bridge}
      />
    )
    expect(screen.getByText('DRIVING KICAD · STEP 3 OF 15')).toBeInTheDocument()
    const bar = screen.getByRole('progressbar', { name: 'Drive progress' })
    expect(bar).toHaveAttribute('aria-valuenow', '3')
    expect(bar).toHaveAttribute('aria-valuemax', '15')
    // Re-rendering a running step does not re-announce it.
    expect(bridge.setDriving).toHaveBeenCalledTimes(1)
  })

  it('renders raw output as text, never as HTML', () => {
    const { container } = render(
      <DriveStrip run={running('<img src=x onerror=alert(1)>\n')} bridge={fakeDriveBridge()} />
    )
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText('DRIVING KICAD · STARTING')).toBeInTheDocument()
  })

  it('clears and tells main the step ended once its output is complete', () => {
    const bridge = fakeDriveBridge()
    const { rerender } = render(<DriveStrip run={running()} bridge={bridge} />)
    rerender(<DriveStrip run={{ ...running(), status: 'finished' }} bridge={bridge} />)
    expect(bridge.setDriving).toHaveBeenLastCalledWith(false)
    expect(screen.queryByText(/DRIVING KICAD/)).toBeNull()
  })

  it('never announces a step that had already ended', () => {
    const bridge = fakeDriveBridge()
    render(<DriveStrip run={{ ...running(), status: 'finished' }} bridge={bridge} />)
    expect(bridge.setDriving).not.toHaveBeenCalled()
  })

  it('tells main the step ended on unmount', () => {
    const bridge = fakeDriveBridge()
    const { unmount } = render(<DriveStrip run={running()} bridge={bridge} />)
    unmount()
    expect(bridge.setDriving).toHaveBeenLastCalledWith(false)
  })

  it('Stop hides the strip and tells main, with no API call', async () => {
    const bridge = fakeDriveBridge()
    render(<DriveStrip run={running('action 2/15 · click · 3.0 s\n')} bridge={bridge} />)
    await userEvent.click(screen.getByRole('button', { name: 'Stop' }))
    expect(bridge.setDriving).toHaveBeenLastCalledWith(false)
    expect(screen.queryByText(/DRIVING KICAD/)).toBeNull()
  })

  it('still renders without the drive bridge', () => {
    render(<DriveStrip run={running()} bridge={null} />)
    expect(screen.getByText('DRIVING KICAD · STARTING')).toBeInTheDocument()
  })
})
