// SOLUSDEV-250 P5 — the level draws cross-links only (no tree connector) and the
// parent chip, the "up" button, sits at the level's anchor.
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Relation } from '../../../lib/api/resources'
import { GraphLinkDrawing } from './GraphLinks'

const relation: Relation = {
  id: 'a-b',
  type: 'connected_to',
  from_entity_id: 'a',
  to_entity_id: 'b'
}
const points = { a: { x: 320, y: 60 }, b: { x: 620, y: 60 } }
const offset = { x: -100, y: -200 }

describe('GraphLinkDrawing', () => {
  it('draws no containment path and keeps cross-links between world points', () => {
    const { container } = render(
      <GraphLinkDrawing
        links={[{ relation, from: 'a', to: 'b' }]}
        points={points}
        offset={offset}
        anchor={{ x: 320, y: 60 }}
        parentName="root"
        onBack={vi.fn()}
      />
    )
    expect(container.querySelector('.graph-containment-edge')).toBeNull()
    expect(container.querySelectorAll('.graph-cross-edge')).toHaveLength(1)
    expect(container.querySelector('.graph-cross-edge')).toHaveAttribute(
      'd',
      'M 420 260 Q 570 200 720 260'
    )
  })

  it('places the parent chip at the anchor and it goes up', () => {
    const onBack = vi.fn()
    render(
      <GraphLinkDrawing
        links={[]}
        points={points}
        offset={offset}
        anchor={{ x: 320, y: 60 }}
        parentName="root"
        onBack={onBack}
      />
    )
    const chip = screen.getByRole('button', { name: 'Back to root' })
    expect(chip.style.left).toBe('420px')
    chip.click()
    expect(onBack).toHaveBeenCalledOnce()
  })

  it('renders no chip at the root level', () => {
    render(
      <GraphLinkDrawing
        links={[]}
        points={points}
        offset={offset}
        anchor={{ x: 0, y: 0 }}
        onBack={vi.fn()}
      />
    )
    expect(screen.queryByRole('button')).toBeNull()
  })
})
