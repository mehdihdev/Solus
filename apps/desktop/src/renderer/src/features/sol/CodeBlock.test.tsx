// SOLUSDEV-317 follow-up (§10.3): the shared code-block surface — plain text,
// a top-right Copy button that copies the block's text and says "Copied" for
// ~1.5 s, and never takes the surface's Cmd/Ctrl+Enter.
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { COPIED_MS, CodeBlock } from './CodeBlock'

afterEach(() => vi.useRealTimers())

describe('CodeBlock', () => {
  it('renders untrusted text as plain text, never HTML', () => {
    const view = render(<CodeBlock kind="output" text={'<img src=x onerror=alert(1)>'} />)
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(view.container.querySelector('img')).toBeNull()
  })

  it('names the button by kind', () => {
    const { rerender } = render(<CodeBlock kind="code" text="a" />)
    expect(screen.getByRole('button', { name: 'Copy code' })).toBeInTheDocument()
    rerender(<CodeBlock kind="output" text="a" />)
    expect(screen.getByRole('button', { name: 'Copy output' })).toBeInTheDocument()
  })

  it('copies the full text even when a shorter view is shown, then reverts after 1.5 s', async () => {
    vi.useFakeTimers()
    const writeText = vi.fn(() => Promise.resolve())
    render(<CodeBlock kind="output" text={'all\nlines'} shown="all" writeText={writeText} />)
    const button = screen.getByRole('button', { name: 'Copy output' })
    await act(async () => {
      fireEvent.click(button)
    })
    expect(writeText).toHaveBeenCalledWith('all\nlines')
    expect(button).toHaveTextContent('Copied')
    expect(screen.getByRole('status')).toHaveTextContent('Copied')
    act(() => {
      vi.advanceTimersByTime(COPIED_MS)
    })
    expect(button).toHaveTextContent('Copy')
  })

  it('stays quiet when the clipboard refuses', async () => {
    const writeText = vi.fn(() => Promise.reject(new Error('denied')))
    render(<CodeBlock kind="code" text="x" writeText={writeText} />)
    const button = screen.getByRole('button', { name: 'Copy code' })
    await act(async () => {
      fireEvent.click(button)
    })
    expect(button).toHaveTextContent('Copy')
  })

  it('is keyboard reachable and lets Cmd/Ctrl+Enter bubble to the surface', () => {
    const surface = vi.fn()
    const writeText = vi.fn(() => Promise.resolve())
    render(
      <div onKeyDown={(e) => surface(e.defaultPrevented)}>
        <CodeBlock kind="output" text="x" writeText={writeText} />
      </div>
    )
    const button = screen.getByRole('button', { name: 'Copy output' })
    button.focus()
    expect(button).toHaveFocus()
    fireEvent.keyDown(button, { key: 'Enter', metaKey: true })
    fireEvent.keyDown(button, { key: 'Enter', ctrlKey: true })
    // Reached the surface (not stopped), with the button's own activation suppressed.
    expect(surface).toHaveBeenCalledTimes(2)
    expect(surface).toHaveBeenCalledWith(true)
    expect(writeText).not.toHaveBeenCalled()
  })

  it('makes output blocks keyboard-scrollable', () => {
    const view = render(<CodeBlock kind="output" text="x" scrollable />)
    expect(view.container.querySelector('pre')?.tabIndex).toBe(0)
  })
})
