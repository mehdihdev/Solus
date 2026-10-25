import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PinnedNodesSection } from './PinnedNodesSection'

const pin = (i: number) => ({
  id: `e${i}`,
  name: `Node ${i}`,
  domain: 'electrical',
  type: 'pcb_board'
})

describe('PinnedNodesSection', () => {
  it('lists pins with a domain dot and type, unpins, and goes to the graph', () => {
    const onUnpin = vi.fn()
    const onFromGraph = vi.fn()
    render(<PinnedNodesSection pins={[pin(1)]} onUnpin={onUnpin} onFromGraph={onFromGraph} />)
    expect(screen.getByText('Node 1')).toBeInTheDocument()
    expect(screen.getByText('pcb board')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Remove Node 1' }))
    expect(onUnpin).toHaveBeenCalledWith('e1')
    fireEvent.click(screen.getByRole('button', { name: 'From graph →' }))
    expect(onFromGraph).toHaveBeenCalledOnce()
  })

  it('explains an empty list and warns past the mention cap', () => {
    const { rerender } = render(
      <PinnedNodesSection pins={[]} onUnpin={vi.fn()} onFromGraph={vi.fn()} />
    )
    expect(screen.getByText(/Pin nodes from the graph/)).toBeInTheDocument()
    rerender(
      <PinnedNodesSection
        pins={Array.from({ length: 9 }, (_, i) => pin(i))}
        onUnpin={vi.fn()}
        onFromGraph={vi.fn()}
      />
    )
    expect(screen.getByRole('note')).toHaveTextContent('Only the first 8 nodes ride along')
  })
})
