// SOLUSDEV-317: an approved command's output, polled while it runs and kept
// (bounded) once it finishes — the wireflow's "Output stays".
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConfirmationOutput } from '../../lib/api/resources.commands'
import {
  MAX_RUN_CHARS,
  MAX_RUN_CHUNKS,
  appendRunOutput,
  newCommandRun,
  startRunPoller,
  type CommandRun
} from './commandRuns'

const output = (over: Partial<ConfirmationOutput>): ConfirmationOutput => ({
  chunks: [],
  cursor: 0,
  complete: false,
  truncated: false,
  ...over
})

describe('appendRunOutput', () => {
  it('appends only chunks past the cursor, as plain text', () => {
    const run = newCommandRun('c1', 'code.exec')
    const first = appendRunOutput(
      { run, cursor: 0 },
      output({
        chunks: [
          { sequence: 1, stream: 'stdout', text: 'a\n' },
          { sequence: 2, stream: 'stderr', text: '<b>' }
        ],
        cursor: 2
      })
    )
    expect(first.run.text).toBe('a\n<b>')
    expect(first.cursor).toBe(2)
    const again = appendRunOutput(
      first,
      output({ chunks: [{ sequence: 2, stream: 'stderr', text: '<b>' }], cursor: 2 })
    )
    expect(again.run.text).toBe('a\n<b>')
    // Immutable: the earlier run is untouched.
    expect(run.text).toBe('')
  })

  it('caps each chunk, the chunk count and the total text', () => {
    const run = newCommandRun('c1', 'code.run')
    const chunks = Array.from({ length: MAX_RUN_CHUNKS + 10 }, (_, i) => ({
      sequence: i + 1,
      stream: 'stdout' as const,
      text: 'x'.repeat(5000)
    }))
    const next = appendRunOutput({ run, cursor: 0 }, output({ chunks, cursor: chunks.length }))
    expect(next.run.text.length).toBeLessThanOrEqual(MAX_RUN_CHARS)
    expect(next.cursor).toBeLessThanOrEqual(MAX_RUN_CHUNKS)
    expect(next.run.truncated).toBe(false)
  })

  it('carries the server truncation marker', () => {
    const next = appendRunOutput(
      { run: newCommandRun('c1', 'code.exec'), cursor: 0 },
      output({ truncated: true })
    )
    expect(next.run.truncated).toBe(true)
  })
})

describe('startRunPoller', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('polls until complete, then stops', async () => {
    const fetchOutput = vi
      .fn()
      .mockResolvedValueOnce(
        output({ chunks: [{ sequence: 1, stream: 'stdout', text: 'one' }], cursor: 1 })
      )
      .mockResolvedValueOnce(
        output({
          chunks: [{ sequence: 2, stream: 'stdout', text: 'two' }],
          cursor: 2,
          complete: true
        })
      )
    const runs: CommandRun[] = []
    startRunPoller(newCommandRun('c1', 'code.exec'), fetchOutput, (run) => runs.push(run))
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchOutput).toHaveBeenLastCalledWith(0)
    await vi.advanceTimersByTimeAsync(750)
    expect(fetchOutput).toHaveBeenLastCalledWith(1)
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetchOutput).toHaveBeenCalledTimes(2)
    expect(runs.at(-1)?.text).toBe('onetwo')
  })

  it('marks progress unavailable on a failed poll and keeps polling', async () => {
    const fetchOutput = vi
      .fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue(output({ complete: true }))
    const runs: CommandRun[] = []
    startRunPoller(newCommandRun('c1', 'code.exec'), fetchOutput, (run) => runs.push(run))
    await vi.advanceTimersByTimeAsync(0)
    expect(runs.at(-1)?.unavailable).toBe(true)
    await vi.advanceTimersByTimeAsync(750)
    expect(runs.at(-1)?.unavailable).toBe(false)
  })

  it('finish() stops the timer and reads the remaining output once', async () => {
    const fetchOutput = vi
      .fn()
      .mockResolvedValueOnce(output({ cursor: 0 }))
      .mockResolvedValueOnce(
        output({ chunks: [{ sequence: 1, stream: 'stdout', text: 'tail' }], cursor: 1 })
      )
    const runs: CommandRun[] = []
    const poller = startRunPoller(newCommandRun('c1', 'code.exec'), fetchOutput, (run) =>
      runs.push(run)
    )
    await vi.advanceTimersByTimeAsync(0)
    await poller.finish()
    expect(runs.at(-1)?.text).toBe('tail')
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetchOutput).toHaveBeenCalledTimes(2)
  })

  it('stop() ends polling without a final read', async () => {
    const fetchOutput = vi.fn().mockResolvedValue(output({}))
    const poller = startRunPoller(newCommandRun('c1', 'code.exec'), fetchOutput, () => undefined)
    await vi.advanceTimersByTimeAsync(0)
    poller.stop()
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetchOutput).toHaveBeenCalledTimes(1)
  })
})
