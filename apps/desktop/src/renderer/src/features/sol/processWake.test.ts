// SOLUSDEV-317 §11.3 "Wake": a NEW prompt_seq on an interactive process this
// conversation started wakes SOL once, never while a turn is streaming.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CodeProcess } from '../../lib/api/resources.commands'
import {
  hasWoken,
  processIdOf,
  processOwner,
  rememberProcessOwner,
  resetProcessOwners,
  MAX_PROCESS_OWNERS
} from './processOwners'
import { wakeWaitingProcesses, type WakeStarter } from './processWake'

const proc = (over: Partial<CodeProcess>): CodeProcess => ({
  process_id: 'pr-1',
  name: 'calibrate',
  argv: ['./calibrate.sh'],
  cwd: '.',
  state: 'running',
  pid: 9,
  exit_code: null,
  started_at: '2026-10-19T10:00:00Z',
  ended_at: null,
  sandbox: 'landlock',
  interactive: true,
  awaiting_input: true,
  prompt_seq: 1,
  prompt_tail: 'Press Enter to continue',
  ...over
})

let start: ReturnType<typeof vi.fn<WakeStarter>>

beforeEach(() => {
  resetProcessOwners()
  start = vi.fn<WakeStarter>().mockReturnValue('started')
})

describe('processOwners', () => {
  it('reads a process id from a process_start outcome value', () => {
    expect(processIdOf({ ok: true, process_id: 'pr-1' })).toBe('pr-1')
    expect(processIdOf({ ok: true, process_id: 7 })).toBeNull()
    expect(processIdOf({ ok: true, process_id: '' })).toBeNull()
    expect(processIdOf(null)).toBeNull()
    expect(processIdOf(undefined)).toBeNull()
  })

  it('remembers which conversation started a process', () => {
    rememberProcessOwner('p', 'pr-1', 'c1')
    expect(processOwner('pr-1')).toEqual({ projectId: 'p', conversationId: 'c1' })
    expect(processOwner('pr-2')).toBeNull()
  })

  it('stays bounded, forgetting the oldest owner first', () => {
    for (let i = 0; i <= MAX_PROCESS_OWNERS; i += 1) rememberProcessOwner('p', `pr-${i}`, 'c')
    expect(processOwner('pr-0')).toBeNull()
    expect(processOwner(`pr-${MAX_PROCESS_OWNERS}`)).not.toBeNull()
  })
})

describe('wakeWaitingProcesses', () => {
  it('wakes the owning conversation with the process prompt', () => {
    rememberProcessOwner('p', 'pr-1', 'c1')
    wakeWaitingProcesses('p', [proc({ prompt_seq: 2 })], 'do', start)
    expect(start).toHaveBeenCalledWith('p', 'c1', { processId: 'pr-1', promptSeq: 2 }, 'do')
    expect(hasWoken('pr-1', 2)).toBe(true)
  })

  it('wakes at most once per (process_id, prompt_seq)', () => {
    rememberProcessOwner('p', 'pr-1', 'c1')
    wakeWaitingProcesses('p', [proc({})], 'do', start)
    wakeWaitingProcesses('p', [proc({})], 'do', start)
    expect(start).toHaveBeenCalledTimes(1)
    wakeWaitingProcesses('p', [proc({ prompt_seq: 2 })], 'do', start)
    expect(start).toHaveBeenCalledTimes(2)
  })

  it('never wakes for a process this renderer did not see started', () => {
    wakeWaitingProcesses('p', [proc({})], 'do', start)
    expect(start).not.toHaveBeenCalled()
  })

  it('never wakes for another project’s process', () => {
    rememberProcessOwner('other', 'pr-1', 'c1')
    wakeWaitingProcesses('p', [proc({})], 'do', start)
    expect(start).not.toHaveBeenCalled()
  })

  it.each([
    ['not interactive', { interactive: false }],
    ['not waiting', { awaiting_input: false }],
    ['no prompt yet', { prompt_seq: 0 }],
    ['not running', { state: 'exited' as const }]
  ])('does not wake when %s', (_label, over) => {
    rememberProcessOwner('p', 'pr-1', 'c1')
    wakeWaitingProcesses('p', [proc(over)], 'do', start)
    expect(start).not.toHaveBeenCalled()
  })

  it('keeps a busy wake queued and retries it on the next poll', () => {
    rememberProcessOwner('p', 'pr-1', 'c1')
    start.mockReturnValueOnce('busy')
    wakeWaitingProcesses('p', [proc({})], 'do', start)
    expect(hasWoken('pr-1', 1)).toBe(false)
    wakeWaitingProcesses('p', [proc({})], 'do', start)
    expect(start).toHaveBeenCalledTimes(2)
    expect(hasWoken('pr-1', 1)).toBe(true)
  })

  it('starts one wake per poll even when several processes wait', () => {
    rememberProcessOwner('p', 'pr-1', 'c1')
    rememberProcessOwner('p', 'pr-2', 'c1')
    wakeWaitingProcesses('p', [proc({}), proc({ process_id: 'pr-2' })], 'do', start)
    expect(start).toHaveBeenCalledTimes(1)
  })

  it('skips a process whose conversation is not open and tries the next', () => {
    rememberProcessOwner('p', 'pr-1', 'c-old')
    rememberProcessOwner('p', 'pr-2', 'c1')
    start.mockImplementation((_p, conversationId) =>
      conversationId === 'c1' ? 'started' : 'elsewhere'
    )
    wakeWaitingProcesses('p', [proc({}), proc({ process_id: 'pr-2' })], 'guide', start)
    expect(start).toHaveBeenLastCalledWith('p', 'c1', { processId: 'pr-2', promptSeq: 1 }, 'guide')
    expect(hasWoken('pr-1', 1)).toBe(false)
  })

  it('forgets owners and woken prompts on reset (identity change)', () => {
    rememberProcessOwner('p', 'pr-1', 'c1')
    wakeWaitingProcesses('p', [proc({})], 'do', start)
    resetProcessOwners()
    expect(processOwner('pr-1')).toBeNull()
    expect(hasWoken('pr-1', 1)).toBe(false)
  })
})
