import { describe, expect, it } from 'vitest'
import type { CodeProcess } from '../../lib/api/resources.commands'
import { elapsed, formatElapsed, programName, stateLabel } from './processStrip.constants'

const proc = (over: Partial<CodeProcess>): CodeProcess => ({
  process_id: 'p-1',
  name: null,
  argv: ['/usr/bin/make'],
  cwd: '.',
  state: 'running',
  pid: 1,
  exit_code: null,
  started_at: '2026-10-18T10:00:00Z',
  ended_at: null,
  sandbox: null,
  interactive: false,
  awaiting_input: false,
  prompt_seq: 0,
  prompt_tail: '',
  ...over
})

describe('process strip helpers', () => {
  it('formats elapsed seconds, minutes and hours', () => {
    expect(formatElapsed(-3)).toBe('0s')
    expect(formatElapsed(59.9)).toBe('59s')
    expect(formatElapsed(61)).toBe('1m 01s')
    expect(formatElapsed(3 * 3600 + 5 * 60)).toBe('3h 05m')
  })

  it('labels every process state', () => {
    expect(stateLabel(proc({ state: 'exited', exit_code: 3 }))).toBe('exited 3')
    expect(stateLabel(proc({ state: 'exited' }))).toBe('exited')
    expect(stateLabel(proc({ state: 'stopped' }))).toBe('stopped')
    expect(stateLabel(proc({ state: 'timed_out' }))).toBe('timed out')
    expect(stateLabel(proc({ state: 'failed_to_start' }))).toBe('failed to start')
  })

  it('names a process by its label, else its program, else its id', () => {
    expect(programName(proc({ name: 'bringup' }))).toBe('bringup')
    expect(programName(proc({}))).toBe('make')
    expect(programName(proc({ argv: [] }))).toBe('p-1')
  })

  it('measures elapsed to the end time, or to when the list was read', () => {
    const readAt = Date.parse('2026-10-18T10:00:10Z')
    expect(elapsed(proc({}), readAt)).toBe('10s')
    expect(elapsed(proc({ ended_at: '2026-10-18T10:00:04Z' }), readAt)).toBe('4s')
    expect(elapsed(proc({ started_at: 'garbage' }), readAt)).toBe('')
  })
})
