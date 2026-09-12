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

function mount(): { onSelect: ReturnType<typeof vi.fn>; onMove: ReturnType<typeof vi.fn> } {
  const onSelect = vi.fn()
  const onMove = vi.fn()
  render(
    <GraphCard
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
})
