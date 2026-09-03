import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Card } from './Card'

describe('Card', () => {
  it('renders children', () => {
    render(<Card>inside</Card>)
    expect(screen.getByText('inside')).toBeInTheDocument()
  })

  it('invokes onClick when clicked', async () => {
    const onClick = vi.fn()
    render(<Card onClick={onClick}>clickable</Card>)
    await userEvent.click(screen.getByText('clickable'))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('reads as clickable (interactive affordance) only when it has an onClick (SOLUSDEV-164)', () => {
    const { rerender } = render(<Card>static</Card>)
    expect(screen.getByText('static').closest('div')).not.toHaveClass('interactive')
    rerender(<Card onClick={vi.fn()}>clickable</Card>)
    expect(screen.getByText('clickable').closest('div')).toHaveClass('interactive')
  })

  it('forwards accessibility attributes but never an HTML sink (SOLUSDEV-235)', () => {
    render(
      <Card
        role="button"
        tabIndex={0}
        aria-label="Open thing"
        // Deliberately bypass the type guard to prove the runtime never forwards it.
        {...({ dangerouslySetInnerHTML: { __html: '<b id="injected">x</b>' } } as object)}
      >
        safe
      </Card>
    )
    const card = screen.getByRole('button', { name: 'Open thing' })
    expect(card).toHaveAttribute('tabindex', '0')
    expect(card).toHaveTextContent('safe')
    expect(document.getElementById('injected')).toBeNull()
  })
})
