// SOLUSDEV-261/317: an approved command's output region. Presentational — the
// store polls (commandRuns.ts); this renders escaped plain text, bounded and
// keyboard-scrollable, and the final exit status once known.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CommandOutput } from './CommandOutput'
import { newCommandRun, type CommandRun } from './commandRuns'

const run = (over: Partial<CommandRun>): CommandRun => ({
  ...newCommandRun('c1', 'code.exec'),
  ...over
})

describe('CommandOutput', () => {
  it('shows escaped output in a keyboard-scrollable region', () => {
    const view = render(<CommandOutput run={run({ text: '<script>progress</script>' })} />)
    expect(screen.getByText('<script>progress</script>')).toBeInTheDocument()
    expect(view.container.querySelector('script')).toBeNull()
    const region = screen.getByLabelText('Command output')
    expect(region.querySelector('pre')?.tabIndex).toBe(0)
  })

  it('waits for output while running', () => {
    render(<CommandOutput run={run({})} />)
    expect(screen.getByText('Waiting for command output…')).toBeInTheDocument()
    expect(screen.queryByText(/exited/)).toBeNull()
  })

  it('reports unavailable progress without implying command failure', () => {
    render(<CommandOutput run={run({ unavailable: true })} />)
    expect(screen.getByText(/Progress unavailable/)).toBeInTheDocument()
  })

  it('renders output in the shared code block with a Copy output button', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<CommandOutput run={run({ text: 'a\nb\n', status: 'exited 0' })} />)
    expect(screen.getByText(/a\s+b/).closest('.code-block')).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Copy output' }))
    expect(writeText).toHaveBeenCalledWith('a\nb\n')
  })

  it('never shows the limit label on completion alone', () => {
    render(<CommandOutput run={run({ text: 'x\n'.repeat(30), status: 'exited 0' })} />)
    expect(screen.queryByText(/Output display limit reached/)).toBeNull()
  })

  it('labels truncation', () => {
    render(<CommandOutput run={run({ text: 'x', truncated: true })} />)
    expect(screen.getByText(/Output display limit reached/)).toBeInTheDocument()
  })

  it('keeps the final output with the exit status', () => {
    render(<CommandOutput run={run({ text: 'done\n', status: 'exited 2' })} />)
    expect(screen.getByText('exited 2')).toBeInTheDocument()
    expect(screen.getByText('done')).toBeInTheDocument()
    expect(screen.queryByText(/Progress unavailable/)).toBeNull()
  })

  it('says there was no output for a finished silent command', () => {
    render(<CommandOutput run={run({ status: 'exited 0' })} />)
    expect(screen.getByText('No output.')).toBeInTheDocument()
  })
})
