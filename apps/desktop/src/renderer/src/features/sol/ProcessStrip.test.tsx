// SOLUSDEV-317: the Running processes strip above the SOL composer
// (sol-page.md "Running processes strip"; code-command-execution.md §6).
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CodeProcess, CodeProcessList } from '../../lib/api/resources.commands'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { ProcessStrip, type ProcessStripDeps } from './ProcessStrip'

const STARTED = '2026-10-18T10:00:00Z'

const proc = (over: Partial<CodeProcess>): CodeProcess => ({
  process_id: 'p-1',
  name: null,
  argv: ['/opt/ros/jazzy/bin/ros2', 'launch', 'bringup.py'],
  cwd: '.',
  state: 'running',
  pid: 42,
  exit_code: null,
  started_at: STARTED,
  ended_at: null,
  sandbox: 'landlock',
  interactive: false,
  awaiting_input: false,
  prompt_seq: 0,
  prompt_tail: '',
  ...over
})

const list = (processes: CodeProcess[], connected = true): CodeProcessList => ({
  bridge: { connected },
  processes
})

function deps(over: Partial<ProcessStripDeps> = {}): ProcessStripDeps {
  return {
    machine: vi.fn().mockResolvedValue({ id: 'm1', name: 'mbp' }),
    listCodeProcesses: vi.fn().mockResolvedValue(list([proc({})])),
    getCodeProcessOutput: vi.fn().mockResolvedValue({ chunks: [], cursor: 0, truncated: false }),
    stopCodeProcess: vi.fn().mockResolvedValue({ ok: true }),
    sendCodeProcessInput: vi.fn().mockResolvedValue({ ok: true, sentChars: 1, reason: null }),
    wake: vi.fn(),
    ...over
  }
}

/** Let the machine lookup and the first list request settle. */
async function settle(): Promise<void> {
  // Machine lookup → render → the scheduled first read → its answer.
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

beforeEach(() => {
  useWorkspaceStore.setState({ linked: true })
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-18T10:01:05Z'))
})
afterEach(() => vi.useRealTimers())

describe('visibility', () => {
  it('is hidden when there are no processes', async () => {
    const d = deps({ listCodeProcesses: vi.fn().mockResolvedValue(list([])) })
    render(<ProcessStrip projectId="proj" deps={d} />)
    await settle()
    expect(d.listCodeProcesses).toHaveBeenCalledWith('proj', 'm1')
    expect(screen.queryByLabelText('Running processes')).toBeNull()
  })

  it('is hidden when the bridge is offline', async () => {
    const d = deps({ listCodeProcesses: vi.fn().mockResolvedValue(list([proc({})], false)) })
    render(<ProcessStrip projectId="proj" deps={d} />)
    await settle()
    expect(screen.queryByLabelText('Running processes')).toBeNull()
  })

  it('never asks without a machine identity', async () => {
    const d = deps({ machine: vi.fn().mockResolvedValue(null) })
    render(<ProcessStrip projectId="proj" deps={d} />)
    await settle()
    expect(d.listCodeProcesses).not.toHaveBeenCalled()
    expect(screen.queryByLabelText('Running processes')).toBeNull()
  })

  it('is hidden when the list request fails', async () => {
    const d = deps({ listCodeProcesses: vi.fn().mockRejectedValue(new Error('offline')) })
    render(<ProcessStrip projectId="proj" deps={d} />)
    await settle()
    expect(screen.queryByLabelText('Running processes')).toBeNull()
  })
})

describe('rows', () => {
  it('shows the program (or name), state and elapsed time as plain text', async () => {
    const d = deps({
      listCodeProcesses: vi.fn().mockResolvedValue(
        list([
          proc({}),
          proc({
            process_id: 'p-2',
            name: '<b>sim</b>',
            state: 'exited',
            exit_code: 0,
            ended_at: '2026-10-18T10:00:30Z'
          })
        ])
      )
    })
    const view = render(<ProcessStrip projectId="proj" deps={d} />)
    await settle()
    const strip = screen.getByLabelText('Running processes')
    const rows = within(strip).getAllByRole('listitem')
    expect(within(rows[0]).getByText('ros2')).toBeInTheDocument()
    expect(within(rows[0]).getByText('running')).toBeInTheDocument()
    expect(within(rows[0]).getByText('1m 05s')).toBeInTheDocument()
    expect(within(rows[1]).getByText('<b>sim</b>')).toBeInTheDocument()
    expect(within(rows[1]).getByText('exited 0')).toBeInTheDocument()
    expect(within(rows[1]).getByText('30s')).toBeInTheDocument()
    expect(view.container.querySelector('b')).toBeNull()
    // Stop only for a running process.
    expect(within(rows[0]).getByRole('button', { name: 'Stop' })).toBeInTheDocument()
    expect(within(rows[1]).queryByRole('button', { name: 'Stop' })).toBeNull()
  })
})

describe('polling cadence', () => {
  it('polls every 2 s while a process runs and every 15 s otherwise', async () => {
    const listFn = vi
      .fn()
      .mockResolvedValueOnce(list([proc({})]))
      .mockResolvedValue(list([proc({ state: 'exited', exit_code: 0, ended_at: STARTED })]))
    render(<ProcessStrip projectId="proj" deps={deps({ listCodeProcesses: listFn })} />)
    await settle()
    expect(listFn).toHaveBeenCalledTimes(1)
    await advance(2000)
    expect(listFn).toHaveBeenCalledTimes(2)
    await advance(2000)
    expect(listFn).toHaveBeenCalledTimes(2)
    await advance(13_000)
    expect(listFn).toHaveBeenCalledTimes(3)
  })

  it('stops polling on unmount', async () => {
    const d = deps()
    const view = render(<ProcessStrip projectId="proj" deps={d} />)
    await settle()
    view.unmount()
    await advance(60_000)
    expect(d.listCodeProcesses).toHaveBeenCalledTimes(1)
  })

  it('reloads when the refresh signal changes', async () => {
    const d = deps()
    const view = render(<ProcessStrip projectId="proj" deps={d} refreshSignal={1} />)
    await settle()
    view.rerender(<ProcessStrip projectId="proj" deps={d} refreshSignal={2} />)
    await settle()
    expect(d.listCodeProcesses).toHaveBeenCalledTimes(2)
  })
})

describe('output', () => {
  it('expands a bounded, keyboard-scrollable plain-text region polled from a cursor', async () => {
    const output = vi
      .fn()
      .mockResolvedValueOnce({
        chunks: [{ seq: 1, stream: 'stdout', text: '<i>ready</i>\n' }],
        cursor: 1,
        truncated: true
      })
      .mockResolvedValue({ chunks: [], cursor: 1, truncated: true })
    const view = render(
      <ProcessStrip projectId="proj" deps={deps({ getCodeProcessOutput: output })} />
    )
    await settle()
    const toggle = screen.getByRole('button', { name: 'Output' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(toggle)
    await settle()
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(output).toHaveBeenCalledWith('proj', 'p-1', 'm1', 0)
    const region = screen.getByLabelText('Process output')
    const pre = region.querySelector('pre')
    expect(pre?.tabIndex).toBe(0)
    expect(pre?.textContent).toBe('<i>ready</i>\n')
    expect(view.container.querySelector('i')).toBeNull()
    expect(within(region).getByText(/Earlier output was dropped/)).toBeInTheDocument()
    await advance(1000)
    expect(output).toHaveBeenLastCalledWith('proj', 'p-1', 'm1', 1)
    fireEvent.click(toggle)
    const calls = output.mock.calls.length
    await advance(5000)
    expect(output.mock.calls.length).toBe(calls)
    expect(screen.queryByLabelText('Process output')).toBeNull()
  })
})

describe('stop', () => {
  it('stops the process as a direct user action, then refreshes', async () => {
    let finish!: () => void
    const stop = vi.fn().mockReturnValue(new Promise<void>((resolve) => (finish = resolve)))
    const d = deps({ stopCodeProcess: stop })
    render(<ProcessStrip projectId="proj" deps={d} />)
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    expect(stop).toHaveBeenCalledWith('proj', 'p-1', 'm1')
    expect(screen.getByRole('button', { name: 'Stopping…' })).toBeDisabled()
    await act(async () => {
      finish()
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(d.listCodeProcesses).toHaveBeenCalledTimes(2)
  })

  it('shows why a stop failed and lets the person try again', async () => {
    const stop = vi.fn().mockRejectedValue(new Error('This machine is offline.'))
    render(<ProcessStrip projectId="proj" deps={deps({ stopCodeProcess: stop })} />)
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    await settle()
    expect(screen.getByRole('alert')).toHaveTextContent('This machine is offline.')
    expect(screen.getByRole('button', { name: 'Stop' })).toBeEnabled()
  })
})
