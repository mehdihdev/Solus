import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { GraphScreen } from './GraphScreen'
import { GRAPH } from '../workspace/workspaceData.constants'
import { useShellStore } from '../workspace/shellStore'

interface Overrides {
  onOpenAlert?: (id: string) => void
  onAskSol?: (key: string) => void
}

function renderGraph(overrides: Overrides = {}): ReturnType<typeof render> {
  return render(
    <GraphScreen
      onOpenAlert={overrides.onOpenAlert ?? vi.fn()}
      onAskSol={overrides.onAskSol ?? vi.fn()}
    />
  )
}

function filterChipFor(label: string): HTMLElement {
  const chip = screen.getAllByText(label).find((el) => el.tagName === 'SPAN')
  if (!chip) throw new Error(`filter chip ${label} missing`)
  return chip
}

beforeEach(() => {
  useShellStore.getState().reset()
})

describe('GraphScreen — canvas', () => {
  it('renders every node of the context model', () => {
    renderGraph()
    for (const node of GRAPH.nodes) {
      expect(screen.getAllByText(node.l).length).toBeGreaterThan(0)
    }
  })

  it('shows the loading state before the model settles', () => {
    renderGraph()
    expect(screen.getByText(/LOADING CONTEXT MODEL/)).toBeInTheDocument()
  })

  it('shows the sync status line and zoom readout', () => {
    renderGraph()
    expect(screen.getByText(/247 NODES · 31 CROSS-DOMAIN LINKS/)).toBeInTheDocument()
    expect(screen.getByText('100%')).toBeInTheDocument()
  })
})

describe('GraphScreen — selection & inspector', () => {
  it('opens the inspector with the clicked node’s properties', async () => {
    renderGraph()
    await userEvent.click(screen.getByText('leg_ik.c'))
    expect(screen.getByText('firmware/src/leg_ik.c')).toBeInTheDocument()
    expect(screen.getByText('Inverse kinematics, per-leg')).toBeInTheDocument()
  })

  it('exposes the open alert of an alert-badged node to onOpenAlert', async () => {
    const onOpenAlert = vi.fn()
    renderGraph({ onOpenAlert })
    // 'drv' is the default selection and carries open alert a1.
    await userEvent.click(screen.getByText('Motor driver swap breaks firmware pin map'))
    expect(onOpenAlert).toHaveBeenCalledWith('a1')
  })

  it('hides the alert chip once the alert is resolved in the shell store', () => {
    useShellStore.getState().resolveAlert('a1')
    renderGraph()
    expect(screen.queryByText('Motor driver swap breaks firmware pin map')).toBeNull()
  })

  it('routes Ask SOL through the alert script for alerted nodes', async () => {
    const onAskSol = vi.fn()
    renderGraph({ onAskSol })
    await userEvent.click(screen.getByRole('button', { name: 'Ask SOL' }))
    expect(onAskSol).toHaveBeenCalledWith('alertq')
  })
})

describe('GraphScreen — domain filter', () => {
  it('toggles a domain off, hiding its nodes', async () => {
    renderGraph()
    expect(screen.getByText('leg_ik.c')).toBeInTheDocument()
    await userEvent.click(filterChipFor('SOFTWARE'))
    expect(screen.queryByText('leg_ik.c')).toBeNull()
    await userEvent.click(filterChipFor('SOFTWARE'))
    expect(screen.getByText('leg_ik.c')).toBeInTheDocument()
  })
})

describe('GraphScreen — view controls', () => {
  it('zooms in, out, and resets', async () => {
    renderGraph()
    await userEvent.click(screen.getByText('+'))
    expect(screen.getByText('118%')).toBeInTheDocument()
    await userEvent.click(screen.getByText('⛶'))
    expect(screen.getByText('100%')).toBeInTheDocument()
    await userEvent.click(screen.getByText('−'))
    expect(screen.getByText('85%')).toBeInTheDocument()
  })

  it('drops same-domain edges in cross-domain-only mode', async () => {
    const { container } = renderGraph()
    const before = container.querySelectorAll('line').length
    await userEvent.click(screen.getByText('CROSS-DOMAIN ONLY'))
    const after = container.querySelectorAll('line').length
    expect(after).toBeLessThan(before)
    expect(after).toBeGreaterThan(0)
  })
})
