// SOLX-02: the persistent orb — always present, click toggles the anchored
// chat panel, drag snaps between corners, detaches to the always-on-top
// window, and pulses only while SOL streams (perf budget: idle costs ~0).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MiniOrb } from './MiniOrb'
import { cornerFor, useOrbStore } from './orbStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { SolWindowBridge } from './solWindowBridge'

vi.mock('./solApi', () => ({
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn().mockResolvedValue([]),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', () => ({ classifyQuery: vi.fn() }))

const w = window as unknown as { solus?: { solWindow: SolWindowBridge } }

beforeEach(() => {
  localStorage.clear()
  useOrbStore.setState({
    corner: 'br',
    expanded: false,
    detached: false,
    streaming: false,
    conversationByProject: {}
  })
  useWorkspaceStore.setState({ teamId: 't1', project: { id: 'p1', name: 'Rover' }, linked: true })
})

afterEach(() => {
  delete w.solus
})

function orbButton(): HTMLElement {
  return screen.getByRole('button', { name: 'Ask SOL' })
}

describe('cornerFor', () => {
  it('snaps to the nearest corner by window midpoints', () => {
    expect(cornerFor(10, 10, 1000, 800)).toBe('tl')
    expect(cornerFor(990, 10, 1000, 800)).toBe('tr')
    expect(cornerFor(10, 790, 1000, 800)).toBe('bl')
    expect(cornerFor(990, 790, 1000, 800)).toBe('br')
  })
})

describe('MiniOrb presence + panel', () => {
  it('renders nothing when hidden', () => {
    const { container } = render(<MiniOrb hidden onClick={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })

  it('is always visible otherwise and toggles the chat panel on click', () => {
    render(<MiniOrb hidden={false} onClick={vi.fn()} />)
    expect(
      screen.queryByPlaceholderText('Ask about a signal, a change, a part…')
    ).not.toBeInTheDocument()
    fireEvent.click(orbButton())
    expect(useOrbStore.getState().expanded).toBe(true)
    expect(screen.getByPlaceholderText('Ask about a signal, a change, a part…')).toBeInTheDocument()
    fireEvent.click(orbButton())
    expect(
      screen.queryByPlaceholderText('Ask about a signal, a change, a part…')
    ).not.toBeInTheDocument()
  })

  it('"Open SOL screen" hands off to the shell (the existing onClick mount) and collapses', () => {
    const onClick = vi.fn()
    render(<MiniOrb hidden={false} onClick={onClick} />)
    fireEvent.click(orbButton())
    fireEvent.click(screen.getByRole('button', { name: 'Open SOL screen' }))
    expect(onClick).toHaveBeenCalledTimes(1)
    expect(useOrbStore.getState().expanded).toBe(false)
  })

  it('pulses only while streaming', () => {
    const { container, rerender } = render(<MiniOrb hidden={false} onClick={vi.fn()} />)
    expect(container.querySelector('.sol-orb-pulse')).toBeNull()
    useOrbStore.getState().setStreaming(true)
    rerender(<MiniOrb hidden={false} onClick={vi.fn()} />)
    expect(container.querySelector('.sol-orb-pulse')).not.toBeNull()
  })
})

describe('MiniOrb dragging', () => {
  it('drag past the threshold snaps the dock to the nearest corner and suppresses the click', () => {
    render(<MiniOrb hidden={false} onClick={vi.fn()} />)
    const btn = orbButton()
    fireEvent.pointerDown(btn, { clientX: 1000, clientY: 700 })
    fireEvent.pointerMove(btn, { clientX: 30, clientY: 40 })
    fireEvent.pointerUp(btn, { clientX: 30, clientY: 40 })
    // Browsers fire click after pointerup — a completed drag must swallow it.
    fireEvent.click(btn)
    expect(useOrbStore.getState().corner).toBe('tl')
    expect(useOrbStore.getState().expanded).toBe(false)
  })

  it('a sub-threshold press is a click, not a drag', () => {
    render(<MiniOrb hidden={false} onClick={vi.fn()} />)
    const btn = orbButton()
    fireEvent.pointerDown(btn, { clientX: 100, clientY: 100 })
    fireEvent.pointerMove(btn, { clientX: 102, clientY: 101 })
    fireEvent.pointerUp(btn, { clientX: 102, clientY: 101 })
    fireEvent.click(btn)
    expect(useOrbStore.getState().corner).toBe('br')
    expect(useOrbStore.getState().expanded).toBe(true)
  })
})

describe('MiniOrb detach/attach', () => {
  it('detaches through the preload bridge and reflects it in the store', async () => {
    const bridge: SolWindowBridge = {
      detach: vi.fn().mockResolvedValue({ detached: true }),
      attach: vi.fn().mockResolvedValue({ detached: false })
    }
    w.solus = { solWindow: bridge }
    render(<MiniOrb hidden={false} onClick={vi.fn()} />)
    fireEvent.click(orbButton())
    fireEvent.click(screen.getByRole('button', { name: 'Detach SOL' }))
    await waitFor(() => expect(useOrbStore.getState().detached).toBe(true))
    expect(bridge.detach).toHaveBeenCalledTimes(1)
    expect(useOrbStore.getState().expanded).toBe(false)

    // Detached: the orb dims into a re-attach affordance.
    const reattach = screen.getByRole('button', { name: /re-attach/i })
    fireEvent.click(reattach)
    await waitFor(() => expect(useOrbStore.getState().detached).toBe(false))
    expect(bridge.attach).toHaveBeenCalledTimes(1)
  })

  it('offers no detach affordance outside Electron', () => {
    render(<MiniOrb hidden={false} onClick={vi.fn()} />)
    fireEvent.click(orbButton())
    expect(screen.queryByRole('button', { name: 'Detach SOL' })).not.toBeInTheDocument()
  })
})
