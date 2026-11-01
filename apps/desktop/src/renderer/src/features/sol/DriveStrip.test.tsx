import { afterEach, describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DriveStrip } from './DriveStrip'
import { newCommandRun, type CommandRun } from './commandRuns'
import { fakeDriveBridge } from '../settings/drive.fixtures'
import type { SolFrontApp } from '../../../../main/drive/frontAppShape'
import { useSolWindowStore } from './solWindowStore'

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
})

describe('DriveStrip — Stop', () => {
  it('Stop shows STOPPING, freezes the bar and keeps the outline until the run ends', async () => {
    const bridge = fakeDriveBridge()
    const run = running('action 2/15 · click · 3.0 s\n')
    const { rerender } = render(<DriveStrip run={run} bridge={bridge} />)
    await userEvent.click(screen.getByRole('button', { name: 'Stop' }))
    expect(screen.getByText('DRIVING KICAD · STOPPING…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Stop' })).toBeDisabled()
    expect(bridge.setDriving).not.toHaveBeenCalledWith(false)
    // A later progress line does not move the frozen bar.
    rerender(
      <DriveStrip
        run={{ ...run, text: run.text + 'action 3/15 · click · 4.0 s\n' }}
        bridge={bridge}
      />
    )
    expect(screen.getByRole('progressbar', { name: 'Drive progress' })).toHaveAttribute(
      'aria-valuenow',
      '2'
    )
    expect(screen.getByText('DRIVING KICAD · STOPPING…')).toBeInTheDocument()
    expect(bridge.setDriving).toHaveBeenCalledTimes(1)
    rerender(<DriveStrip run={{ ...run, status: 'finished' }} bridge={bridge} />)
    expect(bridge.setDriving).toHaveBeenLastCalledWith(false)
    expect(screen.queryByText(/DRIVING KICAD/)).toBeNull()
  })

  it('still renders without the drive bridge', () => {
    render(<DriveStrip run={running()} bridge={null} />)
    expect(screen.getByText('DRIVING KICAD · STARTING')).toBeInTheDocument()
  })
})

describe('DriveStrip app name (SOLUSDEV-319 slice 4)', () => {
  const freecad = (title: string): SolFrontApp => ({
    drivable: true,
    binding: 'window',
    bundleId: 'org.freecad.FreeCAD',
    name: 'FreeCAD',
    pid: 4242,
    windowId: 77,
    title
  })
  afterEach(() => useSolWindowStore.setState({ frontApp: null }))

  it('names the window-bound app in front, upper-cased', () => {
    useSolWindowStore.setState({ frontApp: freecad('bracket_v3.FCStd') })
    render(<DriveStrip run={running('action 2/9 · click · 1.0 s\n')} bridge={fakeDriveBridge()} />)
    expect(screen.getByText('DRIVING FREECAD · STEP 2 OF 9')).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'SOL is driving FreeCAD' })).toBeInTheDocument()
  })

  it('an explicit app name from the step wins; KiCad is the fallback', () => {
    useSolWindowStore.setState({ frontApp: freecad('x') })
    const { rerender } = render(
      <DriveStrip run={running()} appName="Blender" bridge={fakeDriveBridge()} />
    )
    expect(screen.getByText('DRIVING BLENDER · STARTING')).toBeInTheDocument()
    useSolWindowStore.setState({
      frontApp: {
        drivable: true,
        binding: 'project',
        bundleId: 'org.kicad.kicad',
        name: 'KiCad',
        pid: 3,
        windowId: null,
        title: null
      }
    })
    rerender(<DriveStrip run={running()} bridge={fakeDriveBridge()} />)
    expect(screen.getByText('DRIVING KICAD · STARTING')).toBeInTheDocument()
  })

  it('a hostile app name or title renders as text, capped at 24 characters', () => {
    useSolWindowStore.setState({
      frontApp: { ...freecad('<img src=x onerror=alert(1)>'), name: '<img src=x onerror=1>' }
    })
    const { container, unmount } = render(<DriveStrip run={running()} bridge={fakeDriveBridge()} />)
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText('DRIVING <IMG SRC=X ONERROR=1> · STARTING')).toBeInTheDocument()
    unmount()
    useSolWindowStore.setState({ frontApp: { ...freecad('t'), name: 'A'.repeat(40) } })
    render(<DriveStrip run={running()} bridge={fakeDriveBridge()} />)
    expect(screen.getByText(`DRIVING ${'A'.repeat(24)} · STARTING`)).toBeInTheDocument()
  })
})
