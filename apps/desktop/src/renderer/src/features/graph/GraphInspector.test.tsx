import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { GraphInspector } from './GraphInspector'
import { buildNodeIndex, buildNeighbors } from './graphModel'
import { GRAPH, ALERTS } from '../workspace/workspaceData.constants'
import type { GraphNode } from '../workspace/workspaceData.constants'

const byId = buildNodeIndex(GRAPH)
const neighbors = buildNeighbors(GRAPH)

function nodeById(id: string): GraphNode {
  const node = byId[id]
  if (!node) throw new Error(`fixture node ${id} missing`)
  return node
}

interface Overrides {
  node?: GraphNode | null
  onSelect?: (id: string | null) => void
  onOpenAlert?: (id: string) => void
  onAskSol?: (key: string) => void
}

function renderInspector(overrides: Overrides = {}): void {
  render(
    <GraphInspector
      node={overrides.node ?? null}
      alerts={ALERTS}
      byId={byId}
      neighbors={neighbors}
      onSelect={overrides.onSelect ?? vi.fn()}
      onOpenAlert={overrides.onOpenAlert ?? vi.fn()}
      onAskSol={overrides.onAskSol ?? vi.fn()}
    />
  )
}

describe('GraphInspector — empty state', () => {
  it('prompts to select a node when nothing is selected', () => {
    renderInspector({ node: null })
    expect(screen.getByText(/Select a node to inspect it/)).toBeInTheDocument()
  })
})

describe('GraphInspector — node detail', () => {
  it('shows the node label, subtitle, and property rows', () => {
    renderInspector({ node: nodeById('drv') })
    expect(screen.getByText('DRV8316C · U4')).toBeInTheDocument()
    expect(screen.getByText('3-phase BLDC gate driver')).toBeInTheDocument()
    expect(screen.getByText('Package')).toBeInTheDocument()
    expect(screen.getByText('QFN-32 (RSM)')).toBeInTheDocument()
  })

  it('surfaces the open alert as a clickable chip', async () => {
    const onOpenAlert = vi.fn()
    renderInspector({ node: nodeById('drv'), onOpenAlert })
    await userEvent.click(screen.getByText('Motor driver swap breaks firmware pin map'))
    expect(onOpenAlert).toHaveBeenCalledWith('a1')
  })

  it('omits the alert chip for nodes without an open alert', () => {
    renderInspector({ node: nodeById('legik') })
    expect(screen.queryByText('Motor driver swap breaks firmware pin map')).toBeNull()
  })

  it('navigates to a connected node when its row is clicked', async () => {
    const onSelect = vi.fn()
    renderInspector({ node: nodeById('drv'), onSelect })
    await userEvent.click(screen.getByText('M3_PWM'))
    expect(onSelect).toHaveBeenCalledWith('m3pwm')
  })

  it('clears the selection via the close control', async () => {
    const onSelect = vi.fn()
    renderInspector({ node: nodeById('drv'), onSelect })
    await userEvent.click(screen.getByLabelText('Close inspector'))
    expect(onSelect).toHaveBeenCalledWith(null)
  })

  it('labels the open-in button with the domain tool', () => {
    renderInspector({ node: nodeById('drv') })
    expect(screen.getByRole('button', { name: 'Open in KiCad' })).toBeInTheDocument()
  })

  it('asks SOL with the alert script for alert-carrying nodes', async () => {
    const onAskSol = vi.fn()
    renderInspector({ node: nodeById('drv'), onAskSol })
    await userEvent.click(screen.getByRole('button', { name: 'Ask SOL' }))
    expect(onAskSol).toHaveBeenCalledWith('alertq')
  })

  it('asks SOL with the hello script for plain nodes', async () => {
    const onAskSol = vi.fn()
    renderInspector({ node: nodeById('legik'), onAskSol })
    await userEvent.click(screen.getByRole('button', { name: 'Ask SOL' }))
    expect(onAskSol).toHaveBeenCalledWith('hello')
  })
})
