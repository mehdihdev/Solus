// SOLUSDEV-250 P5 — a card carries its domain for the stylesheet and never prints its id.
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { awaitMark, resetMarks, startConfirmation } from '../../../lib/perf/marks'
import type { Entity } from '../../../lib/api/resources'
import { GraphCard } from './GraphCard'

const entity: Entity = {
  id: '0f9c2f2a-1111-4222-8333-444455556666',
  type: 'code_repo',
  name: 'firmware',
  domain: 'code',
  source_key: 'gh:1'
}

afterEach(() => {
  resetMarks()
  performance.clearMarks()
  performance.clearMeasures()
})

function mount(
  finding: { severity: 'info' | 'warning' | 'critical'; count: number } | null = null
): { onSelect: ReturnType<typeof vi.fn>; onMove: ReturnType<typeof vi.fn> } {
  const onSelect = vi.fn()
  const onMove = vi.fn()
  render(
    <GraphCard
      finding={finding}
      entity={entity}
      point={{ x: 0, y: 0 }}
      offset={{ x: 0, y: 0 }}
      focused={false}
      childCount={0}
      onSelect={onSelect}
      onEnter={vi.fn()}
      onBack={vi.fn()}
      onPreview={vi.fn()}
      onMove={onMove}
    />
  )
  return { onSelect, onMove }
}

describe('GraphCard', () => {
  // SOLUSDEV-320 P4-T3 — the badge carries the open count and the worst severity.
  it('shows a finding badge beside the domain dot only when findings are open', () => {
    const { unmount } = render(
      <GraphCard
        entity={entity}
        point={{ x: 0, y: 0 }}
        offset={{ x: 0, y: 0 }}
        focused={false}
        childCount={0}
        onSelect={vi.fn()}
        onEnter={vi.fn()}
        onBack={vi.fn()}
        onPreview={vi.fn()}
        onMove={vi.fn()}
      />
    )
    expect(document.querySelector('.graph-finding-badge')).toBeNull()
    unmount()
    mount({ severity: 'critical', count: 3 })
    const badge = document.querySelector('.graph-finding-badge')
    expect(badge).toHaveAttribute('data-severity', 'critical')
    expect(badge).toHaveTextContent('3')
    expect(badge).toHaveAttribute('title', '3 open findings, worst: critical')
    // The badge rides with the name; the domain dot is the header mark's tile.
    expect(badge?.closest('.graph-node-select')).not.toBeNull()
    expect(document.querySelector('.graph-node-mark .graph-domain-dot')).not.toBeNull()
    expect(screen.getByRole('button', { name: 'Select firmware' })).toBeInTheDocument()
  })

  it('exposes data-domain on the article and shows the name, not the id', () => {
    mount()
    const card = screen.getByTestId(`graph-node-${entity.id}`)
    expect(card).toHaveAttribute('data-domain', 'code')
    expect(card).toHaveTextContent('firmware')
    expect(card.textContent).not.toContain(entity.id)
  })

  it('hands its entity (not a closure) to select and its id to move — stable handlers memoise', () => {
    const { onSelect, onMove } = mount()
    fireEvent.click(screen.getByRole('button', { name: 'Select firmware' }))
    expect(onSelect).toHaveBeenCalledExactlyOnceWith(entity)
    fireEvent.keyDown(screen.getByRole('button', { name: 'Move firmware' }), { key: 'ArrowRight' })
    expect(onMove).toHaveBeenCalledExactlyOnceWith(entity.id, { x: 40, y: 0 })
    expect(performance.getEntriesByName('ws:select_clicked')).toHaveLength(1)
  })

  it('closes hw:confirm_to_node on mount only for the id the confirm awaited', () => {
    mount()
    expect(performance.getEntriesByName('hw:node_visible')).toHaveLength(0)
    awaitMark(entity.id, startConfirmation())
    mount()
    expect(performance.getEntriesByName(`hw:node_visible:${entity.id}`)).toHaveLength(1)
    expect(performance.getEntriesByName(`hw:confirm_to_node:${entity.id}`)).toHaveLength(1)
  })

  // Design template: header mark, mono meta line, footer count; Escape belongs to the navigator.
  it('leads with the Solus mark for .solus, a provider logo for an account anchor, else the domain dot', () => {
    const { rerender } = render(
      <GraphCard
        entity={{ ...entity, type: 'solus_config', name: '.solus' }}
        point={{ x: 0, y: 0 }}
        offset={{ x: 0, y: 0 }}
        focused={false}
        childCount={0}
        onSelect={vi.fn()}
        onEnter={vi.fn()}
        onBack={vi.fn()}
        onPreview={vi.fn()}
        onMove={vi.fn()}
      />
    )
    expect(document.querySelector('.graph-node-mark svg')).not.toBeNull()
    rerender(
      <GraphCard
        entity={{
          ...entity,
          type: 'integration_account',
          domain: 'integration',
          name: 'octocat',
          properties: { provider: 'github' }
        }}
        point={{ x: 0, y: 0 }}
        offset={{ x: 0, y: 0 }}
        focused={false}
        childCount={3}
        onSelect={vi.fn()}
        onEnter={vi.fn()}
        onBack={vi.fn()}
        onPreview={vi.fn()}
        onMove={vi.fn()}
      />
    )
    expect(document.querySelector('.graph-node-mark img')).not.toBeNull()
    expect(screen.getByText('integration account · github')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zoom into octocat' })).toHaveTextContent('3 nodes')
    expect(screen.getByText('double-click to zoom')).toBeInTheDocument()
  })

  it('a leaf says so in the footer and shows its type on the meta line', () => {
    mount()
    expect(document.querySelector('.graph-node-mark .graph-domain-dot')).not.toBeNull()
    expect(screen.getByText('no nodes inside')).toBeInTheDocument()
    expect(screen.getByText('code repo')).toBeInTheDocument()
  })

  it('Escape on the card no longer navigates (the navigator owns it); ArrowLeft still does', () => {
    const onBack = vi.fn()
    render(
      <GraphCard
        entity={entity}
        point={{ x: 0, y: 0 }}
        offset={{ x: 0, y: 0 }}
        focused={false}
        childCount={0}
        onSelect={vi.fn()}
        onEnter={vi.fn()}
        onBack={onBack}
        onPreview={vi.fn()}
        onMove={vi.fn()}
      />
    )
    fireEvent.keyDown(screen.getByRole('button', { name: 'Select firmware' }), { key: 'Escape' })
    expect(onBack).not.toHaveBeenCalled()
    fireEvent.keyDown(screen.getByRole('button', { name: 'Select firmware' }), { key: 'ArrowLeft' })
    expect(onBack).toHaveBeenCalledOnce()
  })
})
