import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AddDocumentRow } from './AddDocumentRow'

const item = { id: 'd1', name: 'Arm', subtitle: 'Part Studio', modified_at: '2026-10-24T00:00:00Z' }

describe('AddDocumentRow', () => {
  it('names the row, shows pick state, and the In graph pill for attached documents', () => {
    const onClick = vi.fn()
    const { rerender } = render(
      <AddDocumentRow item={item} added={false} picked onClick={onClick} busy={false} />
    )
    const row = screen.getByRole('button', { name: 'Arm' })
    expect(row).toHaveAttribute('aria-pressed', 'true')
    expect(row).toHaveTextContent('Part Studio')
    expect(row.querySelector('.add-doc-check')).toHaveAttribute('data-state', 'picked')
    fireEvent.click(row)
    expect(onClick).toHaveBeenCalledOnce()
    rerender(<AddDocumentRow item={item} added picked={false} onClick={onClick} busy />)
    expect(screen.getByRole('button', { name: 'Arm · In graph' })).toBeDisabled()
    expect(screen.getByText('In graph')).toBeInTheDocument()
  })
})
