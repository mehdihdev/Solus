// SOLUSDEV-317 §11.3: the waiting row of an interactive process — badge,
// prompt tail, Send / Enter through the user input route — plus faster polling
// and wake hand-off while anything waits.
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../lib/api/envelope.types'
import type { CodeProcess, CodeProcessList } from '../../lib/api/resources.commands'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { COMPOSER_ATTR } from './commandHotkey'
import { ProcessStrip, type ProcessStripDeps } from './ProcessStrip'

const waiting = (over: Partial<CodeProcess> = {}): CodeProcess => ({
  process_id: 'p-1',
  name: 'calibrate',
  argv: ['./calibrate.sh'],
  cwd: '.',
  state: 'running',
  pid: 42,
  exit_code: null,
  started_at: '2026-10-19T10:00:00Z',
  ended_at: null,
  sandbox: 'landlock',
  interactive: true,
  awaiting_input: true,
  prompt_seq: 1,
  prompt_tail: 'Motor test.\n<b>Continue?</b> [y/n]',
  ...over
})

const list = (processes: CodeProcess[]): CodeProcessList => ({
  bridge: { connected: true },
  processes
})

function deps(over: Partial<ProcessStripDeps> = {}): ProcessStripDeps {
  return {
    machine: vi.fn().mockResolvedValue({ id: 'm1', name: 'mbp' }),
    listCodeProcesses: vi.fn().mockResolvedValue(list([waiting()])),
    getCodeProcessOutput: vi.fn().mockResolvedValue({ chunks: [], cursor: 0, truncated: false }),
    stopCodeProcess: vi.fn().mockResolvedValue({ ok: true }),
    sendCodeProcessInput: vi.fn().mockResolvedValue({ ok: true, sentChars: 2, reason: null }),
    wake: vi.fn(),
    ...over
  }
}

async function settle(): Promise<void> {
  for (let i = 0; i < 3; i += 1) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
  }
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

const inputBox = (): HTMLInputElement => screen.getByRole('textbox', { name: /Input for/ })

beforeEach(() => {
  useWorkspaceStore.setState({ linked: true })
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-19T10:01:00Z'))
})
afterEach(() => vi.useRealTimers())

describe('waiting row', () => {
  it('shows the badge, the prompt tail as plain text with Copy, an input, Send and Enter', async () => {
    const view = render(<ProcessStrip projectId="proj" deps={deps()} />)
    await settle()
    const row = screen.getByRole('listitem')
    expect(within(row).getByText('Waiting for input')).toBeInTheDocument()
    expect(row.querySelector('pre')?.textContent).toBe('Motor test.\n<b>Continue?</b> [y/n]')
    expect(view.container.querySelector('b')).toBeNull()
    expect(within(row).getByRole('button', { name: 'Copy output' })).toBeInTheDocument()
    expect(inputBox()).toHaveAttribute('maxlength', '1024')
    expect(within(row).getByRole('button', { name: 'Send' })).toBeDisabled()
    expect(within(row).getByRole('button', { name: 'Enter' })).toBeEnabled()
  })

  it('shows no waiting row for a process that is not waiting', async () => {
    const d = deps({
      listCodeProcesses: vi.fn().mockResolvedValue(list([waiting({ awaiting_input: false })]))
    })
    render(<ProcessStrip projectId="proj" deps={d} />)
    await settle()
    expect(screen.queryByText('Waiting for input')).toBeNull()
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it('marks the input as a draft so Cmd/Ctrl+Enter there never approves a card', async () => {
    render(<ProcessStrip projectId="proj" deps={deps()} />)
    await settle()
    expect(inputBox()).toHaveAttribute(COMPOSER_ATTR)
  })

  it('Send posts the text plus Enter, clears the input and refreshes', async () => {
    let finish!: (v: unknown) => void
    const send = vi.fn().mockReturnValue(new Promise((resolve) => (finish = resolve)))
    const d = deps({ sendCodeProcessInput: send })
    render(<ProcessStrip projectId="proj" deps={d} />)
    await settle()
    fireEvent.change(inputBox(), { target: { value: 'y' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(send).toHaveBeenCalledWith('proj', 'p-1', 'm1', { text: 'y', enter: true })
    expect(screen.getByRole('button', { name: 'Sending…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Enter' })).toBeDisabled()
    await act(async () => {
      finish({ ok: true, sentChars: 2, reason: null })
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(inputBox().value).toBe('')
    expect(d.listCodeProcesses).toHaveBeenCalledTimes(2)
  })

  it('pressing Enter in the input sends like Send', async () => {
    const d = deps()
    render(<ProcessStrip projectId="proj" deps={d} />)
    await settle()
    fireEvent.change(inputBox(), { target: { value: 'yes' } })
    fireEvent.submit(inputBox().closest('form') as HTMLFormElement)
    expect(d.sendCodeProcessInput).toHaveBeenCalledWith('proj', 'p-1', 'm1', {
      text: 'yes',
      enter: true
    })
  })

  it('Enter sends a bare Enter and keeps any draft', async () => {
    const d = deps()
    render(<ProcessStrip projectId="proj" deps={d} />)
    await settle()
    fireEvent.change(inputBox(), { target: { value: 'draft' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enter' }))
    expect(d.sendCodeProcessInput).toHaveBeenCalledWith('proj', 'p-1', 'm1', {
      text: '',
      enter: true
    })
    await settle()
    expect(inputBox().value).toBe('draft')
  })
})

describe('failed sends', () => {
  it.each([
    [new ApiError(409, 'not_waiting', 'x'), 'No longer waiting'],
    [new ApiError(409, 'bridge_offline', 'x'), /offline/],
    [new ApiError(404, 'not_found', 'x'), /no longer running/],
    [new ApiError(500, 'boom', 'internal detail'), 'That input could not be sent.'],
    [new Error('Input can’t contain control characters.'), /control characters/]
  ])('explains a failed send (%s) and keeps the text', async (error, text) => {
    const d = deps({ sendCodeProcessInput: vi.fn().mockRejectedValue(error) })
    render(<ProcessStrip projectId="proj" deps={d} />)
    await settle()
    fireEvent.change(inputBox(), { target: { value: 'y' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await settle()
    expect(screen.getByRole('alert')).toHaveTextContent(text)
    expect(screen.getByRole('alert')).not.toHaveTextContent('internal detail')
    expect(inputBox().value).toBe('y')
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled()
  })

  it('treats a refused answer as a failed send', async () => {
    const send = vi.fn().mockResolvedValue({ ok: false, sentChars: 0, reason: 'not running' })
    render(<ProcessStrip projectId="proj" deps={deps({ sendCodeProcessInput: send })} />)
    await settle()
    fireEvent.change(inputBox(), { target: { value: 'y' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await settle()
    expect(screen.getByRole('alert')).toHaveTextContent('That input could not be sent.')
    expect(inputBox().value).toBe('y')
  })
})

describe('polling while waiting', () => {
  it('polls every 1 s while any process waits for input', async () => {
    const d = deps()
    render(<ProcessStrip projectId="proj" deps={d} />)
    await settle()
    expect(d.listCodeProcesses).toHaveBeenCalledTimes(1)
    await advance(1000)
    expect(d.listCodeProcesses).toHaveBeenCalledTimes(2)
    await advance(1000)
    expect(d.listCodeProcesses).toHaveBeenCalledTimes(3)
  })
})

describe('wake hand-off', () => {
  it('hands every fresh list to the waker with the surface’s action mode', async () => {
    const d = deps()
    render(<ProcessStrip projectId="proj" deps={d} actionMode="do" />)
    await settle()
    expect(d.wake).toHaveBeenCalledWith('proj', [waiting()], 'do')
  })

  it('uses the latest action mode without refetching', async () => {
    const d = deps()
    const view = render(<ProcessStrip projectId="proj" deps={d} actionMode="do" />)
    await settle()
    view.rerender(<ProcessStrip projectId="proj" deps={d} actionMode="guide" />)
    await advance(1000)
    expect(d.listCodeProcesses).toHaveBeenCalledTimes(2)
    expect(d.wake).toHaveBeenLastCalledWith('proj', [waiting()], 'guide')
  })

  it('never wakes without an action mode', async () => {
    const d = deps()
    render(<ProcessStrip projectId="proj" deps={d} />)
    await settle()
    expect(d.wake).not.toHaveBeenCalled()
  })
})
