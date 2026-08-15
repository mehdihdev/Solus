// SOLX-03 composition root. Exercises the PRODUCTION path — the preload surface
// on `window.solus`, not an injected port — because the one thing a unit test of
// the pieces cannot catch is the overlay window mounting and never subscribing.
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, act, cleanup } from '@testing-library/react'
import {
  createLoopbackPorts,
  createStubOrb,
  type GuideStep,
  type OrbPort,
  type ToolWindowRef
} from '@solus/shared-types'
import { OverlayWindow } from './OverlayWindow'

const TARGET: ToolWindowRef = {
  tool: 'kicad',
  windowTitle: 'KiCad Schematic Editor',
  displayId: null,
  bounds: { x: 0, y: 0, width: 1200, height: 800 }
}

const STEP: GuideStep = {
  stepId: 'place-symbol',
  index: 0,
  total: 3,
  title: 'Place a symbol',
  instruction: 'Press A to open the symbol chooser.',
  control: {
    tool: 'kicad',
    controlId: 'place-symbol',
    locator: { x: 0.1, y: 0.2, w: 0.2, h: 0.05 }
  }
}

/** Stand in for the preload: a loopback whose orb end the test drives. */
function installBridge(): OrbPort {
  const { orb, overlay } = createLoopbackPorts()
  const w = window as unknown as { solus?: unknown }
  w.solus = {
    orbOverlay: {
      publishToOrb: overlay.send,
      onOrbToOverlay: overlay.subscribe
    }
  }
  return orb
}

afterEach(() => {
  cleanup()
  delete (window as unknown as { solus?: unknown }).solus
})

describe('OverlayWindow', () => {
  it('draws nothing until the orb spawns a handoff', () => {
    installBridge()
    const { container } = render(<OverlayWindow />)
    expect(container).toBeEmptyDOMElement()
  })

  it('paints the pointer for a spawned step', () => {
    const orb = installBridge()
    render(<OverlayWindow />)
    act(() => {
      createStubOrb(orb).spawn({ handoffId: 'h1', focus: null, step: STEP, target: TARGET })
    })
    expect(screen.getByTestId('overlay-pointer')).toBeInTheDocument()
    expect(screen.getByText('Place a symbol')).toBeInTheDocument()
  })

  it('clears the surface when the handoff is dismissed', () => {
    const orb = installBridge()
    const { container } = render(<OverlayWindow />)
    const driver = createStubOrb(orb)
    act(() => driver.spawn({ handoffId: 'h1', focus: null, step: STEP, target: TARGET }))
    act(() => driver.dismiss('user_dismissed'))
    expect(container).toBeEmptyDOMElement()
  })

  it('unsubscribes on unmount, so a closed overlay stops reacting', () => {
    const orb = installBridge()
    const { unmount } = render(<OverlayWindow />)
    unmount()
    expect(() =>
      act(() => {
        createStubOrb(orb).spawn({ handoffId: 'h1', focus: null, step: STEP, target: TARGET })
      })
    ).not.toThrow()
    expect(screen.queryByTestId('overlay-pointer')).not.toBeInTheDocument()
  })

  it('renders nothing at all outside Electron, where there is no bridge', () => {
    // Static preview (`pnpm build` + serve out/renderer) loads every hash route.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { container } = render(<OverlayWindow />)
    expect(container).toBeEmptyDOMElement()
    spy.mockRestore()
  })
})
