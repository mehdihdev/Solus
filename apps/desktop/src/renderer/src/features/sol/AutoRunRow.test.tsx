// SOLUSDEV-317 follow-up (code-command-execution.md §10.3): a Build-mode
// code.exec that ran without a card shows as a compact command row — program
// basename, status and an `auto` label — over a code-block output collapsed
// beyond 12 lines. Copy always copies the full retained output.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AutoRun } from '../../lib/api/solStream'
import { AUTO_RUN_VISIBLE_LINES, AutoRunRow } from './AutoRunRow'

const row = (over: Partial<AutoRun> = {}): AutoRun => ({
  callId: 'c1',
  program: 'ls',
  status: 'exited 0',
  output: 'a\nb\n',
  ...over
})

describe('AutoRunRow', () => {
  it('shows the program, status and an auto label', () => {
    render(<AutoRunRow run={row({ status: 'timed out' })} />)
    const group = screen.getByRole('group', { name: 'Command ls, timed out, ran automatically' })
    expect(group).toHaveTextContent('ls')
    expect(group).toHaveTextContent('timed out')
    expect(group).toHaveTextContent('auto')
  })

  it('renders output as plain text in the code block', () => {
    const view = render(<AutoRunRow run={row({ output: '<script>x</script>' })} />)
    expect(screen.getByText('<script>x</script>').closest('.code-block')).not.toBeNull()
    expect(view.container.querySelector('script')).toBeNull()
  })

  it('collapses beyond 12 lines, expands on toggle, and copies the full text', () => {
    const lines = Array.from({ length: 20 }, (_, i) => `line ${i + 1}`)
    const output = `${lines.join('\n')}\n`
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<AutoRunRow run={row({ output })} />)
    const code = (): HTMLElement => screen.getByText(/line 1\b/)
    expect(code()).toHaveTextContent(`line ${AUTO_RUN_VISIBLE_LINES}`)
    expect(code()).not.toHaveTextContent(`line ${AUTO_RUN_VISIBLE_LINES + 1}`)
    const toggle = screen.getByRole('button', { name: 'Show all 20 lines' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(screen.getByRole('button', { name: 'Copy output' }))
    expect(writeText).toHaveBeenCalledWith(output)
    fireEvent.click(toggle)
    expect(code()).toHaveTextContent('line 20')
    expect(screen.getByRole('button', { name: 'Show fewer lines' })).toHaveAttribute(
      'aria-expanded',
      'true'
    )
  })

  it('has no toggle for short output and no block for none', () => {
    const { rerender } = render(<AutoRunRow run={row()} />)
    expect(screen.queryByRole('button', { name: /Show/ })).toBeNull()
    rerender(<AutoRunRow run={row({ output: '' })} />)
    expect(screen.queryByRole('button', { name: 'Copy output' })).toBeNull()
    expect(screen.getByText('No output.')).toBeInTheDocument()
  })
})
