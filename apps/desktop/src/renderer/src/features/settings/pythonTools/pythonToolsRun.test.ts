// SOLUSDEV-329 — folding mcpRuntime:progress pushes into one run.
import { describe, expect, it } from 'vitest'
import {
  acceptPush,
  applyRunEvent,
  failedForks,
  firstFailingCode,
  forksNeedingSetup,
  isRunning,
  newRun
} from './pythonToolsRun'
import type { ForkStatus, RuntimeEvent } from '../../../../../main/mcpRuntime/protocol'

const DONE: RuntimeEvent = { type: 'done', outcome: 'failed', ok: 0, failed: 1, skipped: 0 }
const FAIL: RuntimeEvent = {
  type: 'fork_result',
  fork: 'code',
  outcome: 'failed',
  error_code: 'pip_failed',
  message: ''
}

describe('pythonToolsRun', () => {
  it('adopts the first push id while pending, then ignores other runs', () => {
    const run = acceptPush(newRun('provision', 'settings'), 'r1', FAIL)
    expect(run?.runId).toBe('r1')
    expect(acceptPush(run, 'r2', DONE)).toBe(run)
  })

  it('records progress per fork and globally, and stops at done', () => {
    let run = newRun('install', 'settings')
    run = applyRunEvent(run, { type: 'progress', fork: null, step: 'download', done: 1, total: 2 })
    run = applyRunEvent(run, {
      type: 'progress',
      fork: 'kicad',
      step: 'venv',
      done: 0,
      total: null
    })
    expect(run.global?.step).toBe('download')
    expect(run.progress.kicad.step).toBe('venv')
    run = applyRunEvent(run, DONE)
    expect(isRunning(run)).toBe(false)
    expect(applyRunEvent(run, FAIL)).toBe(run)
  })

  it('first failing code prefers a tool result, then the run error', () => {
    let run = applyRunEvent(newRun('provision', 'settings'), {
      type: 'error',
      error_code: 'network_unreachable',
      message: ''
    })
    expect(firstFailingCode(run)).toBe('network_unreachable')
    run = applyRunEvent(run, FAIL)
    expect(firstFailingCode(run)).toBe('pip_failed')
    expect(failedForks(run)).toEqual(['code'])
    expect(firstFailingCode(newRun('provision', 'settings'))).toBeNull()
  })

  it('a new choice marks every OS-supported tool as needing setup', () => {
    const forks: ForkStatus[] = [
      {
        type: 'status',
        fork: 'kicad',
        state: 'ready',
        detail: null,
        base_version: '3.12.7',
        managed: false
      },
      {
        type: 'status',
        fork: 'altium',
        state: 'unsupported_platform',
        detail: null,
        base_version: null,
        managed: false
      },
      {
        type: 'status',
        fork: 'code',
        state: 'needs_setup',
        detail: 'needs_setup:no_env',
        base_version: null,
        managed: false
      }
    ]
    expect(forksNeedingSetup(forks, false)).toEqual(['code'])
    expect(forksNeedingSetup(forks, true)).toEqual(['kicad', 'code'])
  })
})
