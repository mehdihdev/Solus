// SOLUSDEV-327 — sidebar header, greeting and resize handle.
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ResizeHandle, SidebarGreeting, SidebarHeader, SolOrbDot } from './SidebarParts'

describe('SidebarHeader', () => {
  it('shows SOL and the tag, and wires its buttons', () => {
    const props = { onPopOut: vi.fn(), onExpand: vi.fn(), onClose: vi.fn() }
    render(<SidebarHeader tag="LIVE BENCH" working={false} {...props} />)
    expect(screen.getByText('SOL')).toBeInTheDocument()
    expect(screen.getByText('LIVE BENCH')).toHaveAttribute('title', 'LIVE BENCH')
    fireEvent.click(screen.getByRole('button', { name: 'Pop out to the pill' }))
    fireEvent.click(screen.getByRole('button', { name: 'Open in the SOL page' }))
    fireEvent.click(screen.getByRole('button', { name: 'Close SOL sidebar' }))
    expect(props.onPopOut).toHaveBeenCalled()
    expect(props.onExpand).toHaveBeenCalled()
    expect(props.onClose).toHaveBeenCalled()
  })

  it('omits pop-out without a SOL window', () => {
    render(<SidebarHeader tag="HOME" working={false} onExpand={vi.fn()} onClose={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Pop out to the pill' })).toBeNull()
  })
})

describe('SolOrbDot', () => {
  it('quickens while working', () => {
    const { container, rerender } = render(<SolOrbDot working={false} />)
    expect(container.firstChild).not.toHaveClass('sol-pulse')
    rerender(<SolOrbDot working />)
    expect(container.firstChild).toHaveClass('sol-orb', 'sol-pulse')
  })
})

describe('SidebarGreeting', () => {
  it('renders the greeting and sends a chip', () => {
    const onAsk = vi.fn()
    render(<SidebarGreeting greeting="Hello" suggestions={['One?', 'Two?']} onAsk={onAsk} />)
    expect(screen.getByText('Hello')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Two?' }))
    expect(onAsk).toHaveBeenCalledWith('Two?')
  })

  it('draws no chip row without suggestions', () => {
    const { container } = render(<SidebarGreeting greeting="Hi" suggestions={[]} onAsk={vi.fn()} />)
    expect(container.querySelector('.sol-sb-chips')).toBeNull()
  })
})

describe('ResizeHandle', () => {
  it('is a focusable vertical separator carrying the width', () => {
    const resize = { width: 360, onPointerDown: vi.fn(), onKeyDown: vi.fn() }
    render(<ResizeHandle resize={resize} />)
    const handle = screen.getByRole('separator', { name: 'Resize SOL sidebar' })
    expect(handle).toHaveAttribute('aria-valuenow', '360')
    expect(handle).toHaveAttribute('tabindex', '0')
    fireEvent.keyDown(handle, { key: 'ArrowLeft' })
    expect(resize.onKeyDown).toHaveBeenCalled()
  })
})
