import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ContextMenu, clampMenuPosition } from './ContextMenu'

describe('clampMenuPosition', () => {
  it('keeps the menu box inside the viewport', () => {
    const { x, y } = clampMenuPosition(window.innerWidth + 50, window.innerHeight + 50, {
      width: 200,
      height: 100
    })
    expect(x).toBe(window.innerWidth - 200)
    expect(y).toBe(window.innerHeight - 100)
    expect(clampMenuPosition(-5, -5)).toEqual({ x: 0, y: 0 })
  })
})

describe('ContextMenu', () => {
  it('renders the title and items, selects then closes', () => {
    const onClose = vi.fn()
    const onSelect = vi.fn()
    render(
      <ContextMenu
        x={10}
        y={10}
        title="Project details"
        items={[
          { label: 'Import files…', onSelect },
          { label: 'Ask SOL to find…', onSelect: vi.fn(), disabled: true, hint: 'SOL is busy' }
        ]}
        onClose={onClose}
      />
    )
    expect(screen.getByText('PROJECT DETAILS')).toBeInTheDocument()
    const busy = screen.getByRole('menuitem', { name: /Ask SOL to find/ })
    expect(busy).toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(busy)
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('menuitem', { name: /Import files/ }))
    expect(onSelect).toHaveBeenCalledOnce()
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('closes on backdrop click', () => {
    const onClose = vi.fn()
    render(<ContextMenu x={0} y={0} items={[]} onClose={onClose} />)
    fireEvent.click(screen.getByTestId('context-menu-backdrop'))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
