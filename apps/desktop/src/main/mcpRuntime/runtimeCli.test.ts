// SOLUSDEV-329 — spawning `solus-companion runtime …` from desktop main
// (docs/architecture/mcp-fork-runtime.md §6, §9): argv only, never a shell;
// bounded, validated stdout; timeout and cancellation kill the child.
import { EventEmitter } from 'node:events'
import { PassThrough } from 'node:stream'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  CANCEL_GRACE_MS,
  runtimeArgv,
  startRuntimeRun,
  type RuntimeChild,
  type RuntimeSpawn
} from './runtimeCli'
import type { RuntimeEvent } from './protocol'

const BASE = { command: '/app/companion/solus-companion', args: [] as string[] }
const DEV = { command: 'uv', args: ['run', '--no-sync', 'python', '-m', 'solus_companion'] }

describe('runtimeArgv', () => {
  it('appends the runtime subcommand to the companion command', () => {
    expect(runtimeArgv(DEV, { command: 'detect' })).toEqual({
      command: 'uv',
      args: ['run', '--no-sync', 'python', '-m', 'solus_companion', 'runtime', 'detect']
    })
    expect(runtimeArgv(BASE, { command: 'status' }).args).toEqual(['runtime', 'status'])
    expect(runtimeArgv(BASE, { command: 'install-managed' }).args).toEqual([
      'runtime',
      'install-managed'
    ])
  })

  it('provision: --all or repeated --fork, then the interpreter choice', () => {
    expect(
      runtimeArgv(BASE, { command: 'provision', python: { mode: 'auto', path: null } }).args
    ).toEqual(['runtime', 'provision', '--all'])
    expect(
      runtimeArgv(BASE, {
        command: 'provision',
        forks: ['kicad', 'local'],
        python: { mode: 'path', path: '/opt/homebrew/bin/python3.12' }
      }).args
    ).toEqual([
      'runtime',
      'provision',
      '--fork',
      'kicad',
      '--fork',
      'local',
      '--python',
      '/opt/homebrew/bin/python3.12'
    ])
    expect(
      runtimeArgv(BASE, { command: 'provision', python: { mode: 'managed', path: null } }).args
    ).toEqual(['runtime', 'provision', '--all', '--managed'])
  })

  it('refuses a fork name that could be read as a flag or a path', () => {
    for (const fork of ['--all', '../x', 'KiCad', '', 'a'.repeat(33)]) {
      expect(() =>
        runtimeArgv(BASE, {
          command: 'provision',
          forks: [fork],
          python: { mode: 'auto', path: null }
        })
      ).toThrow()
    }
  })

  it('refuses a relative or flag-like interpreter path', () => {
    for (const path of ['python3', '--managed', '', 'a\0b']) {
      expect(() =>
        runtimeArgv(BASE, { command: 'provision', python: { mode: 'path', path } })
      ).toThrow()
    }
  })

  it('never routes through a shell', () => {
    const { command, args } = runtimeArgv(BASE, { command: 'detect' })
    for (const part of [command, ...args]) {
      expect(part).not.toMatch(/^(\/bin\/)?(ba|z)?sh$|cmd(\.exe)?$|powershell/i)
      expect(part).not.toBe('-c')
    }
  })
})

class FakeChild extends EventEmitter implements RuntimeChild {
  stdout = new PassThrough()
  stderr = new PassThrough()
  pid = 4242
  exitCode: number | null = null
  line(obj: Record<string, unknown>): void {
    this.stdout.write(`${JSON.stringify({ v: 1, ...obj })}\n`)
  }
  async finish(code: number | null): Promise<void> {
    this.stdout.end()
    this.stderr.end()
    await new Promise((r) => setImmediate(r))
    this.exitCode = code
    this.emit('close', code, null)
  }
}

function harness(): {
  child: FakeChild
  spawn: ReturnType<typeof vi.fn> & RuntimeSpawn
  kill: ReturnType<typeof vi.fn>
  events: RuntimeEvent[]
  start: (timeoutMs?: number) => ReturnType<typeof startRuntimeRun>
} {
  const child = new FakeChild()
  const spawn = vi.fn(() => child) as unknown as ReturnType<typeof vi.fn> & RuntimeSpawn
  const kill = vi.fn()
  const events: RuntimeEvent[] = []
  return {
    child,
    spawn,
    kill,
    events,
    start: (timeoutMs = 60_000) =>
      startRuntimeRun(
        runtimeArgv(DEV, { command: 'detect' }),
        { PATH: '/usr/bin' },
        { onEvent: (e) => events.push(e), timeoutMs, deps: { spawn, kill } }
      )
  }
}

const DONE_OK = { type: 'done', outcome: 'ok', ok: 1, failed: 0, skipped: 0 }

describe('startRuntimeRun', () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] }))
  afterEach(() => vi.useRealTimers())

  it('spawns with an argv array, no shell, and the given env', async () => {
    const h = harness()
    const run = h.start()
    expect(h.spawn).toHaveBeenCalledTimes(1)
    const [command, args, options] = h.spawn.mock.calls[0]
    expect(command).toBe('uv')
    expect(args).toEqual([
      'run',
      '--no-sync',
      'python',
      '-m',
      'solus_companion',
      'runtime',
      'detect'
    ])
    expect(options).toMatchObject({ shell: false, env: { PATH: '/usr/bin' } })
    h.child.line(DONE_OK)
    await h.child.finish(0)
    await expect(run.result).resolves.toMatchObject({ exitCode: 0, done: DONE_OK, dropped: 0 })
  })

  it('delivers validated events and counts dropped lines', async () => {
    const h = harness()
    const run = h.start()
    h.child.stdout.write('garbage\n')
    h.child.line({ type: 'error', error_code: 'internal', message: 'x' })
    h.child.line(DONE_OK)
    await h.child.finish(0)
    const result = await run.result
    expect(h.events.map((e) => e.type)).toEqual(['error', 'done'])
    expect(result.dropped).toBe(1)
    expect(result.synthesized).toBe(false)
  })

  it('cancel signals the child, escalates after the grace, and synthesizes done cancelled', async () => {
    const h = harness()
    const run = h.start()
    run.cancel()
    expect(h.kill).toHaveBeenCalledWith(4242, 'SIGTERM')
    vi.advanceTimersByTime(CANCEL_GRACE_MS + 1)
    expect(h.kill).toHaveBeenCalledWith(4242, 'SIGKILL')
    await h.child.finish(null)
    const result = await run.result
    expect(result.done).toEqual({
      type: 'done',
      outcome: 'cancelled',
      ok: 0,
      failed: 0,
      skipped: 0
    })
    expect(result.synthesized).toBe(true)
    expect(h.events.at(-1)).toEqual(result.done)
    expect(h.events).toContainEqual(expect.objectContaining({ error_code: 'cancelled' }))
  })

  it('no SIGKILL when the child exits within the grace', async () => {
    const h = harness()
    const run = h.start()
    run.cancel()
    h.child.line({ type: 'done', outcome: 'cancelled', ok: 0, failed: 0, skipped: 0 })
    await h.child.finish(130)
    vi.advanceTimersByTime(CANCEL_GRACE_MS + 1)
    expect(h.kill).not.toHaveBeenCalledWith(4242, 'SIGKILL')
    expect((await run.result).synthesized).toBe(false)
  })

  it('a timeout kills the child and ends as failed / timeout', async () => {
    const h = harness()
    const run = h.start(1_000)
    vi.advanceTimersByTime(1_001)
    expect(h.kill).toHaveBeenCalledWith(4242, 'SIGTERM')
    await h.child.finish(null)
    const result = await run.result
    expect(result.done.outcome).toBe('failed')
    expect(h.events).toContainEqual(
      expect.objectContaining({ type: 'error', error_code: 'timeout' })
    )
  })

  it('a child that exits without done ends as failed / internal', async () => {
    const h = harness()
    const run = h.start()
    await h.child.finish(2)
    const result = await run.result
    expect(result).toMatchObject({ exitCode: 2, synthesized: true })
    expect(result.done.outcome).toBe('failed')
    expect(h.events[0]).toMatchObject({ type: 'error', error_code: 'internal' })
  })

  it('a spawn error settles once as failed', async () => {
    const h = harness()
    const run = h.start()
    h.child.emit('error', new Error('ENOENT'))
    await h.child.finish(null)
    const result = await run.result
    expect(result.done.outcome).toBe('failed')
    expect(h.events.filter((e) => e.type === 'done')).toHaveLength(1)
  })

  it('a synchronous spawn throw resolves failed instead of throwing', async () => {
    const spawn = vi.fn(() => {
      throw new Error('bad env')
    }) as unknown as RuntimeSpawn
    const run = startRuntimeRun(
      BASE,
      {},
      { onEvent: () => undefined, timeoutMs: 1_000, deps: { spawn, kill: vi.fn() } }
    )
    await expect(run.result).resolves.toMatchObject({
      synthesized: true,
      done: { outcome: 'failed' }
    })
  })

  it('ignores anything after the first done', async () => {
    const h = harness()
    const run = h.start()
    h.child.line(DONE_OK)
    h.child.line({ type: 'error', error_code: 'internal', message: 'late' })
    await h.child.finish(0)
    await run.result
    expect(h.events.map((e) => e.type)).toEqual(['done'])
  })
})
