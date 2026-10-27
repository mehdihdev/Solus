// SOLUSDEV-319 drive slice 3b (sol-drive.md §5 "Main and the agent"): in dev
// main runs the debug helper as `serve --socket-dir <drive-dev>` while drive
// is wanted, stops it when not, and restarts it with backoff if it dies.
import { EventEmitter } from 'node:events'
import { describe, expect, it, vi } from 'vitest'
import {
  createDevAgentSupervisor,
  devAgentRestartDelayMs,
  type DevAgentDeps
} from './driveDevAgent'

class FakeChild extends EventEmitter {
  killed: string[] = []
  exitCode: number | null = null
  kill(signal: string): boolean {
    this.killed.push(signal)
    return true
  }
}

function harness(): {
  deps: DevAgentDeps
  children: FakeChild[]
  spawn: ReturnType<typeof vi.fn>
  timers: Array<{ cb: () => void; ms: number }>
  runTimers(): void
} {
  const children: FakeChild[] = []
  const timers: Array<{ cb: () => void; ms: number }> = []
  const spawn = vi.fn(() => {
    const c = new FakeChild()
    children.push(c)
    return c
  })
  return {
    children,
    spawn,
    timers,
    runTimers: () => timers.splice(0).forEach((t) => t.cb()),
    deps: {
      spawn,
      prepareDir: vi.fn(),
      setTimeout: (cb, ms) => {
        timers.push({ cb, ms })
        return timers.length
      },
      clearTimeout: () => undefined,
      now: () => 0
    }
  }
}

const H = '/repo/.build/out/Products/Debug/solus-input'
const DIR = '/Users/me/Library/Application Support/Solus/drive-dev'

describe('createDevAgentSupervisor', () => {
  it('spawns `serve --socket-dir` with an argument list and a PATH-only env', () => {
    const h = harness()
    createDevAgentSupervisor(h.deps).set({ helper: H, socketDir: DIR })
    expect(h.spawn).toHaveBeenCalledWith(H, ['serve', '--socket-dir', DIR], {
      env: { PATH: '/usr/bin:/bin' },
      stdio: 'ignore',
      shell: false
    })
    expect(h.deps.prepareDir).toHaveBeenCalledWith(DIR)
  })

  it('a repeated identical want does not respawn; a different helper does', () => {
    const h = harness()
    const s = createDevAgentSupervisor(h.deps)
    s.set({ helper: H, socketDir: DIR })
    s.set({ helper: H, socketDir: DIR })
    expect(h.spawn).toHaveBeenCalledTimes(1)
    s.set({ helper: '/other', socketDir: DIR })
    expect(h.spawn).toHaveBeenCalledTimes(2)
    expect(h.children[0].killed).toEqual(['SIGTERM'])
  })

  it('stops the child when drive is no longer wanted, and does not restart it', () => {
    const h = harness()
    const s = createDevAgentSupervisor(h.deps)
    s.set({ helper: H, socketDir: DIR })
    s.set(null)
    expect(h.children[0].killed).toEqual(['SIGTERM'])
    h.children[0].emit('exit', 0)
    h.runTimers()
    expect(h.spawn).toHaveBeenCalledTimes(1)
  })

  it('restarts a child that died, with backoff', () => {
    const h = harness()
    const s = createDevAgentSupervisor(h.deps)
    s.set({ helper: H, socketDir: DIR })
    h.children[0].emit('exit', 1)
    expect(h.timers[0].ms).toBe(devAgentRestartDelayMs(0))
    h.runTimers()
    expect(h.spawn).toHaveBeenCalledTimes(2)
    h.children[1].emit('error', new Error('ENOENT'))
    expect(h.timers[0].ms).toBe(devAgentRestartDelayMs(1))
  })

  it('a spawn that throws is retried like a crash', () => {
    const h = harness()
    h.spawn.mockImplementationOnce(() => {
      throw new Error('EACCES')
    })
    createDevAgentSupervisor(h.deps).set({ helper: H, socketDir: DIR })
    expect(h.timers).toHaveLength(1)
    h.runTimers()
    expect(h.spawn).toHaveBeenCalledTimes(2)
  })

  it('backoff doubles from 1 s and caps at 30 s', () => {
    expect([0, 1, 2, 10].map(devAgentRestartDelayMs)).toEqual([1_000, 2_000, 4_000, 30_000])
  })
})
