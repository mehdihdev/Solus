// SOLUSDEV-317 — typed clients for command output and the Running processes
// strip (docs/api/code-command-execution.md §6, code-environment.md output route).
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient, RequestOptions } from './client'
import {
  getCodeProcessOutput,
  getConfirmationOutput,
  listCodeProcesses,
  sendCodeProcessInput,
  stopCodeProcess
} from './resources.commands'

function stubClient(result: unknown): {
  client: ApiClient
  calls: { path: string; options?: RequestOptions }[]
} {
  const calls: { path: string; options?: RequestOptions }[] = []
  const client: ApiClient = {
    request: vi.fn(async (path: string, options?: RequestOptions) => {
      calls.push({ path, options })
      return result as never
    }),
    requestPage: vi.fn(async () => {
      throw new Error('unused')
    })
  }
  return { client, calls }
}

describe('getConfirmationOutput', () => {
  it('GETs the owner-scoped output route with the cursor, ids encoded', async () => {
    const { client, calls } = stubClient({ chunks: [], cursor: 0, complete: false })
    const result = await getConfirmationOutput('p/1', 'c 1', 3, client)
    expect(calls[0].path).toBe('/projects/p%2F1/sol/confirmations/c%201/output?cursor=3')
    expect(result).toEqual({ chunks: [], cursor: 0, complete: false, truncated: false })
  })

  it('drops malformed chunks', async () => {
    const { client } = stubClient({
      chunks: [
        { sequence: 1, stream: 'stdout', text: 'ok' },
        { sequence: 'x', stream: 'stdout', text: 'bad' },
        { sequence: 2, stream: 'other', text: 'bad' },
        null
      ],
      cursor: 2,
      complete: true,
      truncated: true
    })
    const result = await getConfirmationOutput('p', 'c', 0, client)
    expect(result.chunks).toEqual([{ sequence: 1, stream: 'stdout', text: 'ok' }])
    expect(result.complete).toBe(true)
    expect(result.truncated).toBe(true)
  })
})

const GOOD = {
  process_id: 'a',
  name: null,
  argv: ['/opt/ros/jazzy/bin/ros2', 'launch'],
  cwd: '.',
  state: 'running',
  pid: 1,
  exit_code: null,
  started_at: '2026-10-18T10:00:00Z',
  ended_at: null,
  sandbox: 'landlock'
}
const NOT_INTERACTIVE = {
  interactive: false,
  awaiting_input: false,
  prompt_seq: 0,
  prompt_tail: ''
}

describe('code processes', () => {
  it('lists this machine’s processes and widens an offline answer', async () => {
    const { client, calls } = stubClient({ bridge: { connected: false } })
    const result = await listCodeProcesses('p1', 'm 1', client)
    expect(calls[0].path).toBe('/projects/p1/code/processes?machine_id=m%201')
    expect(result).toEqual({ bridge: { connected: false }, processes: [] })
  })

  it('keeps well-formed process rows only', async () => {
    const good = {
      process_id: 'a',
      name: null,
      argv: ['/opt/ros/jazzy/bin/ros2', 'launch'],
      cwd: '.',
      state: 'running',
      pid: 1,
      exit_code: null,
      started_at: '2026-10-18T10:00:00Z',
      ended_at: null,
      sandbox: 'landlock'
    }
    const { client } = stubClient({
      bridge: { connected: true },
      processes: [good, { process_id: 7 }, { ...good, process_id: 'b', state: 'weird' }]
    })
    const result = await listCodeProcesses('p1', 'm1', client)
    expect(result.processes).toEqual([{ ...good, ...NOT_INTERACTIVE }])
  })
})

describe('interactive process fields (§11.1)', () => {
  it('reads the interactive fields and defaults them when absent', async () => {
    const waiting = {
      ...GOOD,
      interactive: true,
      awaiting_input: true,
      prompt_seq: 3,
      prompt_tail: 'Calibrate now? [y/n]'
    }
    const { client } = stubClient({ bridge: { connected: true }, processes: [waiting, GOOD] })
    const result = await listCodeProcesses('p1', 'm1', client)
    expect(result.processes[0]).toMatchObject({
      interactive: true,
      awaiting_input: true,
      prompt_seq: 3,
      prompt_tail: 'Calibrate now? [y/n]'
    })
    expect(result.processes[1]).toMatchObject(NOT_INTERACTIVE)
  })

  it('narrows malformed interactive fields to safe values', async () => {
    const junk = {
      ...GOOD,
      interactive: 'yes',
      awaiting_input: 1,
      prompt_seq: -2.5,
      prompt_tail: { html: '<b>' }
    }
    const { client } = stubClient({ bridge: { connected: true }, processes: [junk] })
    const [row] = (await listCodeProcesses('p1', 'm1', client)).processes
    expect(row).toMatchObject(NOT_INTERACTIVE)
  })

  it('never waits on a process that is not interactive and running, and caps the tail', async () => {
    const odd = {
      ...GOOD,
      state: 'exited',
      interactive: true,
      awaiting_input: true,
      prompt_seq: 1,
      prompt_tail: 'x'.repeat(5000)
    }
    const { client } = stubClient({ bridge: { connected: true }, processes: [odd] })
    const [row] = (await listCodeProcesses('p1', 'm1', client)).processes
    expect(row.awaiting_input).toBe(false)
    expect(row.prompt_tail).toHaveLength(1024)
  })
})

describe('process output and stop', () => {
  it('reads one process’s output from a cursor', async () => {
    const { client, calls } = stubClient({
      output: {
        process_id: 'a',
        chunks: [{ seq: 4, stream: 'stderr', text: 'warn' }],
        cursor: 4,
        truncated: true
      }
    })
    const result = await getCodeProcessOutput('p1', 'a', 'm1', 2, client)
    expect(calls[0].path).toBe('/projects/p1/code/processes/a/output?machine_id=m1&cursor=2')
    expect(result).toEqual({
      chunks: [{ seq: 4, stream: 'stderr', text: 'warn' }],
      cursor: 4,
      truncated: true
    })
  })

  it('POSTs the user’s own stop', async () => {
    const { client, calls } = stubClient({ ok: true, process_id: 'a', state: 'stopped' })
    await stopCodeProcess('p1', 'a', 'm1', client)
    expect(calls[0].path).toBe('/projects/p1/code/processes/a/stop?machine_id=m1')
    expect(calls[0].options).toEqual({ method: 'POST' })
  })
})

describe('sendCodeProcessInput (§11.2 user input route)', () => {
  it('POSTs text and enter to the owner-scoped input route, ids encoded', async () => {
    const { client, calls } = stubClient({ ok: true, process_id: 'a b', sent_chars: 2 })
    const result = await sendCodeProcessInput(
      'p1',
      'a b',
      'm 1',
      { text: 'y', enter: true },
      client
    )
    expect(calls[0].path).toBe('/projects/p1/code/processes/a%20b/input?machine_id=m%201')
    expect(calls[0].options).toEqual({ method: 'POST', body: { text: 'y', enter: true } })
    expect(result).toEqual({ ok: true, sentChars: 2, reason: null })
  })

  it('sends a bare Enter as empty text', async () => {
    const { client, calls } = stubClient({ ok: true, sent_chars: 1 })
    await sendCodeProcessInput('p1', 'a', 'm1', { text: '', enter: true }, client)
    expect(calls[0].options?.body).toEqual({ text: '', enter: true })
  })

  it('narrows a refusal answer defensively', async () => {
    const { client } = stubClient({ ok: false, sent_chars: 'x', reason: 'not running' })
    const result = await sendCodeProcessInput('p1', 'a', 'm1', { text: 'y', enter: true }, client)
    expect(result).toEqual({ ok: false, sentChars: 0, reason: 'not running' })
  })

  it('refuses control characters and over-long text before any request', async () => {
    const { client } = stubClient({ ok: true })
    await expect(
      sendCodeProcessInput('p1', 'a', 'm1', { text: 'a\tb', enter: true }, client)
    ).rejects.toThrow(/control characters/)
    await expect(
      sendCodeProcessInput('p1', 'a', 'm1', { text: 'x'.repeat(1025), enter: true }, client)
    ).rejects.toThrow(/1024/)
    expect(client.request).not.toHaveBeenCalled()
  })
})
