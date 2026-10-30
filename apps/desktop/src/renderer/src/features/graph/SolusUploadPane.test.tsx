import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SolusUploadPane } from './SolusUploadPane'

describe('SolusUploadPane', () => {
  it('names the target, opens the picker on click and hands dropped files over', () => {
    const onChoose = vi.fn()
    const onDrop = vi.fn()
    render(<SolusUploadPane target="Documentation" onChoose={onChoose} onDrop={onDrop} />)
    const zone = screen.getByRole('button', { name: 'Upload documents' })
    expect(zone).toHaveTextContent('saved to .solus › Documentation')
    fireEvent.click(zone)
    expect(onChoose).toHaveBeenCalledOnce()
    const a = new File(['a'], 'a.md', { type: 'text/markdown' })
    const b = new File(['b'], 'b.pdf', { type: 'application/pdf' })
    fireEvent.drop(zone, { dataTransfer: { files: [a, b] } })
    expect(onDrop).toHaveBeenCalledWith([a, b])
    fireEvent.drop(zone, { dataTransfer: { files: [] } })
    expect(onDrop).toHaveBeenCalledTimes(1)
  })
})
