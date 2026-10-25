import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Entity } from '../../../lib/api/resources'
import { GraphBreadcrumb, levelStat } from './GraphBreadcrumb'

const entity = (id: string, name: string): Entity => ({
  id,
  name,
  type: 'pcb',
  domain: 'electrical',
  source_key: null
})
const A = entity('a', 'Main board')
const B = entity('b', 'Power stage')

describe('GraphBreadcrumb', () => {
  it('at the root shows only Graph, no back arrow, and the whole-canvas stat', () => {
    render(<GraphBreadcrumb trail={[]} level={4} total={96} onGo={vi.fn()} onBack={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Graph' })).toHaveAttribute(
      'aria-current',
      'location'
    )
    expect(screen.queryByRole('button', { name: 'Zoom out (Esc)' })).toBeNull()
    expect(screen.getByText('4 ROOTS · 96 NODES · DOUBLE-CLICK TO ZOOM IN')).toBeInTheDocument()
  })

  it('deeper in, lists the trail, goes to a crumb or the root, and backs out', () => {
    const onGo = vi.fn()
    const onBack = vi.fn()
    render(<GraphBreadcrumb trail={[A, B]} level={3} total={96} onGo={onGo} onBack={onBack} />)
    expect(screen.getByRole('navigation', { name: 'Graph trail' })).toHaveTextContent(
      'Graph›Main board›Power stage'
    )
    expect(screen.getByText('3 NODES INSIDE · ESC TO ZOOM OUT')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Main board' }))
    expect(onGo).toHaveBeenLastCalledWith(A)
    fireEvent.click(screen.getByRole('button', { name: 'Graph' }))
    expect(onGo).toHaveBeenLastCalledWith(null)
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out (Esc)' }))
    expect(onBack).toHaveBeenCalledOnce()
  })

  it('levelStat is pure', () => {
    expect(levelStat([], 1, 1)).toBe('1 ROOTS · 1 NODES · DOUBLE-CLICK TO ZOOM IN')
    expect(levelStat([A], 0, 9)).toBe('0 NODES INSIDE · ESC TO ZOOM OUT')
  })
})
