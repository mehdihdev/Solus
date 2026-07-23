import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Button } from './Button'

describe('Button', () => {
  it('renders its children', () => {
    render(<Button>Create account</Button>)
    expect(screen.getByRole('button', { name: 'Create account' })).toBeInTheDocument()
  })

  it('calls onClick when enabled', async () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Go</Button>)
    await userEvent.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('does not call onClick when disabled', async () => {
    const onClick = vi.fn()
    render(
      <Button onClick={onClick} disabled>
        Go
      </Button>
    )
    await userEvent.click(screen.getByRole('button'))
    expect(onClick).not.toHaveBeenCalled()
  })

  it('defaults to type="button" so it never submits a form implicitly', () => {
    render(<Button>Go</Button>)
    expect(screen.getByRole('button')).toHaveAttribute('type', 'button')
  })

  it('carries the interactive affordance class when enabled (SOLUSDEV-164)', () => {
    render(<Button>Go</Button>)
    expect(screen.getByRole('button')).toHaveClass('interactive')
  })

  it('drops the interactive class when disabled so a dead button gives no feedback', () => {
    render(<Button disabled>Go</Button>)
    expect(screen.getByRole('button')).not.toHaveClass('interactive')
  })

  it('preserves a caller-provided className alongside the affordance class', () => {
    render(<Button className="custom">Go</Button>)
    const button = screen.getByRole('button')
    expect(button).toHaveClass('custom')
    expect(button).toHaveClass('interactive')
  })
})
