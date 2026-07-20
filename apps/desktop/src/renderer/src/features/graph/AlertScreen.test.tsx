// Alert detail screen (SOLUSDEV-152): the fabricated demo alerts, the fake
// apply-fix/PR animation, and the scripted diffs are gone. Until live
// cross-domain alerts exist, this is an honest empty state.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { AlertScreen } from './AlertScreen'

describe('AlertScreen — honest empty state', () => {
  it('explains what alerts will show and what enables them', () => {
    render(<AlertScreen onBack={vi.fn()} />)
    expect(screen.getByText('No alert to show')).toBeInTheDocument()
    expect(screen.getByText(/SOL raises the alert here/)).toBeInTheDocument()
    expect(screen.getByText(/Connect sources/)).toBeInTheDocument()
  })

  it('navigates back via the back link', () => {
    const onBack = vi.fn()
    render(<AlertScreen onBack={onBack} />)
    fireEvent.click(screen.getByText('Back'))
    expect(onBack).toHaveBeenCalled()
  })

  it('contains no fabricated fix flow or PR references', () => {
    const { container } = render(<AlertScreen onBack={vi.fn()} />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/Opening PR|#144|Apply fix|strider/i)
    expect(text).not.toMatch(/DRV8316C|motor_driver\.c/)
    expect(text).not.toMatch(/CONFIDENCE/)
  })
})
