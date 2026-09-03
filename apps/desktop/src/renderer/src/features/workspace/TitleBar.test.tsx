// SOLUSDEV-235 — the window title row: a drag region that hosts the project pill.
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { TitleBar } from './TitleBar'

const w = window as unknown as { solus?: { platform?: string } }

afterEach(() => {
  delete w.solus
})

describe('TitleBar', () => {
  it('renders its slot inside a draggable region', () => {
    render(
      <TitleBar>
        <span>Rover MK3</span>
      </TitleBar>
    )
    expect(screen.getByText('Rover MK3')).toBeInTheDocument()
    expect(screen.getByTestId('title-bar')).toHaveClass('app-drag')
  })

  it('insets for the macOS traffic lights only under Electron on darwin', () => {
    const { unmount } = render(<TitleBar>x</TitleBar>)
    expect(screen.getByTestId('title-bar')).toHaveAttribute('data-inset', 'none')
    unmount()
    w.solus = { platform: 'darwin' }
    render(<TitleBar>x</TitleBar>)
    expect(screen.getByTestId('title-bar')).toHaveAttribute('data-inset', 'mac')
  })
})
