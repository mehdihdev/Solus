// Pure decision logic of the companion supervisor (SOLUSDEV-154 / BRG-04):
// command resolution, backoff schedule, pidfile parsing/orphan reap, and the
// newline-JSON token framing. Process supervision itself is exercised on the
// Linux ARM validation checklist (docs/companion-packaging.md), not in vitest.
import { describe, it, expect, vi, type MockInstance } from 'vitest'

// companion.ts touches electron `app` only inside its impure functions; mock
// the module so the import works under the test runner (as oauthLoopback does).
vi.mock('electron', () => ({
  app: { isPackaged: false, getPath: () => '/tmp/solus-test', getAppPath: () => '/tmp/solus-test' }
}))

import {
  resolveCompanionCommand,
  backoffDelayMs,
  nextRestartAttempt,
  parsePidfile,
  shouldReapPid,
  isCompanionCmdline,
  tokenLine,
  credentialLine,
  credentialInputError,
  writeCredential,
  BACKOFF_BASE_MS,
  BACKOFF_CAP_MS,
  BACKOFF_RESET_UPTIME_MS
} from './companion'

const SENTINEL = 'SENTINEL-NOT-A-REAL-LICENSE'

describe('resolveCompanionCommand', () => {
  const base = { isPackaged: true, resourcesPath: '/opt/Solus/resources', env: {} }

  it('resolves the packaged binary under resources/companion', () => {
    expect(resolveCompanionCommand({ ...base, platform: 'linux' })).toEqual({
      command: '/opt/Solus/resources/companion/solus-companion',
      args: []
    })
  })

  it('macOS runs the PyInstaller onedir binary (sol-drive.md §5)', () => {
    expect(resolveCompanionCommand({ ...base, platform: 'darwin' })).toEqual({
      command: '/opt/Solus/resources/companion/solus-companion/solus-companion',
      args: []
    })
  })

  it('appends .exe on win32', () => {
    expect(resolveCompanionCommand({ ...base, platform: 'win32' })?.command).toBe(
      '/opt/Solus/resources/companion/solus-companion.exe'
    )
  })

  it('splits SOLUS_COMPANION_DEV_CMD on whitespace in dev', () => {
    expect(
      resolveCompanionCommand({
        isPackaged: false,
        resourcesPath: '',
        platform: 'linux',
        env: { SOLUS_COMPANION_DEV_CMD: 'uv run  python -m solus_companion' }
      })
    ).toEqual({ command: 'uv', args: ['run', 'python', '-m', 'solus_companion'] })
  })

  it('disables the companion in dev when the env var is absent or blank', () => {
    const dev = { isPackaged: false, resourcesPath: '', platform: 'linux' } as const
    expect(resolveCompanionCommand({ ...dev, env: {} })).toBeNull()
    expect(resolveCompanionCommand({ ...dev, env: { SOLUS_COMPANION_DEV_CMD: '   ' } })).toBeNull()
  })
})

describe('backoffDelayMs', () => {
  it('doubles from 1 s and caps at 30 s (upper jitter bound)', () => {
    const top = (): number => 1
    expect(backoffDelayMs(0, top)).toBe(BACKOFF_BASE_MS)
    expect(backoffDelayMs(1, top)).toBe(2000)
    expect(backoffDelayMs(2, top)).toBe(4000)
    expect(backoffDelayMs(4, top)).toBe(16000)
    expect(backoffDelayMs(5, top)).toBe(BACKOFF_CAP_MS)
    expect(backoffDelayMs(50, top)).toBe(BACKOFF_CAP_MS)
  })

  it('jitters down to half the exponential step, never below', () => {
    const bottom = (): number => 0
    expect(backoffDelayMs(0, bottom)).toBe(BACKOFF_BASE_MS / 2)
    expect(backoffDelayMs(5, bottom)).toBe(BACKOFF_CAP_MS / 2)
    const d = backoffDelayMs(3)
    expect(d).toBeGreaterThanOrEqual(4000)
    expect(d).toBeLessThanOrEqual(8000)
  })
})

describe('nextRestartAttempt', () => {
  it('escalates on rapid exits and resets after stable uptime', () => {
    expect(nextRestartAttempt(-1, 100)).toBe(0)
    expect(nextRestartAttempt(0, 5000)).toBe(1)
    expect(nextRestartAttempt(3, BACKOFF_RESET_UPTIME_MS - 1)).toBe(4)
    expect(nextRestartAttempt(3, BACKOFF_RESET_UPTIME_MS)).toBe(0)
  })
})

describe('parsePidfile', () => {
  it('parses a positive pid and rejects everything else', () => {
    expect(parsePidfile('1234\n')).toBe(1234)
    expect(parsePidfile(' 42 ')).toBe(42)
    expect(parsePidfile('')).toBeNull()
    expect(parsePidfile('garbage')).toBeNull()
    expect(parsePidfile('-5')).toBeNull()
    expect(parsePidfile('0')).toBeNull()
    expect(parsePidfile('12.5')).toBeNull()
  })
})

describe('shouldReapPid', () => {
  const alive = (): boolean => true
  const dead = (): boolean => false

  it('reaps only a live pid from a previous run', () => {
    expect(shouldReapPid(1234, alive)).toBe(true)
    expect(shouldReapPid(1234, dead)).toBe(false)
    expect(shouldReapPid(null, alive)).toBe(false)
  })
})

describe('isCompanionCmdline', () => {
  it('recognizes the packaged binary', () => {
    expect(isCompanionCmdline('/opt/Solus/resources/companion/solus-companion')).toBe(true)
    expect(isCompanionCmdline('C:\\Solus\\resources\\companion\\solus-companion.exe')).toBe(true)
  })

  it('recognizes the dev module run (NUL-separated /proc form and ps form)', () => {
    expect(isCompanionCmdline('/usr/bin/python3\0-m\0solus_companion\0')).toBe(true)
    expect(isCompanionCmdline('python -m solus_companion')).toBe(true)
  })

  it('rejects an unrelated process that recycled the pid', () => {
    expect(isCompanionCmdline('/usr/bin/node /home/x/server.js')).toBe(false)
    expect(isCompanionCmdline('')).toBe(false)
  })
})

describe('tokenLine', () => {
  it('frames a token as newline-delimited JSON', () => {
    expect(tokenLine('sb-access-token')).toBe('{"type":"token","access_token":"sb-access-token"}\n')
  })

  it('frames null as a signout', () => {
    expect(tokenLine(null)).toBe('{"type":"signout"}\n')
  })
})

// BYO-license capture relay (SOLUSDEV-102 / MCP-05): renderer → preload →
// main → companion stdin ONLY. Values never logged, never persisted.
describe('credentialLine', () => {
  it('frames server and secrets as exactly one newline-delimited JSON line', () => {
    expect(credentialLine('altium', { altium_license: SENTINEL })).toBe(
      `{"type":"credential","server":"altium","secrets":{"altium_license":"${SENTINEL}"}}\n`
    )
  })
})

describe('credentialInputError', () => {
  it('accepts a flat non-empty string-to-string secrets object', () => {
    expect(credentialInputError('altium', { altium_license: 'v' })).toBeNull()
  })

  it('rejects invalid shapes with static errors that never echo a value', () => {
    const cases: Array<[unknown, unknown]> = [
      [42, { k: SENTINEL }],
      ['', { k: SENTINEL }],
      ['altium', null],
      ['altium', 'string'],
      ['altium', [SENTINEL]],
      ['altium', {}],
      ['altium', { k: 42 }],
      ['altium', { '': SENTINEL }],
      ['altium', { k: { nested: SENTINEL } }]
    ]
    for (const [server, secrets] of cases) {
      const error = credentialInputError(server, secrets)
      expect(error).not.toBeNull()
      expect(error).not.toContain(SENTINEL)
    }
  })

  it('rejects an oversize secrets object with a static error (M4)', () => {
    // A giant secrets payload would frame a stdin line the companion drops
    // (its 16 KiB control cap) — reject it here so it never reaches stdin.
    const huge = 'A'.repeat(64 * 1024)
    const error = credentialInputError('altium', { altium_license: huge })
    expect(error).toBe('secrets too large')
  })
})

describe('writeCredential', () => {
  it('rejects with a clear error when the companion is not running', () => {
    // Module-singleton child is null here (startCompanion never ran).
    expect(writeCredential('altium', { altium_license: 'v' })).toEqual({
      ok: false,
      error: 'companion not running'
    })
  })

  it('rejects invalid renderer input before touching the process', () => {
    expect(writeCredential(42, { k: 'v' })).toEqual({ ok: false, error: 'invalid server name' })
    expect(writeCredential('altium', 'nope')).toEqual({ ok: false, error: 'invalid secrets' })
  })

  it('never logs secret values on any path', () => {
    const spies = (['log', 'warn', 'error', 'info', 'debug'] as const).map((level) =>
      vi.spyOn(console, level).mockImplementation(() => undefined)
    )
    try {
      writeCredential('altium', { altium_license: SENTINEL })
      writeCredential(42, { altium_license: SENTINEL })
      writeCredential('altium', { altium_license: { deep: SENTINEL } })
      for (const spy of spies) {
        for (const call of spy.mock.calls) {
          expect(JSON.stringify(call)).not.toContain(SENTINEL)
        }
      }
    } finally {
      spies.forEach((spy) => spy.mockRestore())
    }
  })
})

describe('project switch (SOLUSDEV-253)', () => {
  /** A child that ignores SIGTERM: python with no spaces inside the -c code,
   *  because the dev command splits on whitespace. */
  const STUBBORN = "python3 -c __import__('signal').signal(15,1);__import__('time').sleep(30)"
  const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))
  const signals = (kill: KillSpy, sig: string): number[] =>
    kill.mock.calls.filter(([, s]) => s === sig).map(([pid]) => pid as number)

  it('kills the previous companion PROCESS GROUP, not just the uv wrapper', async () => {
    // A real, harmless child (no module mocks): the supervisor spawns it detached
    // in its own group, and replacing the project must signal that GROUP —
    // signalling only the wrapper pid left the companion alive and the old and
    // new sessions superseding each other on the bridge.
    await withSupervisor('sleep 30', async (companion, kill) => {
      companion.setCompanionProject('project-a')
      kill.mockClear()
      companion.setCompanionProject('project-b')
      const termed = signals(kill, 'SIGTERM')
      expect(termed).toHaveLength(1)
      expect(termed[0]).toBeLessThan(0) // negative pid ⇒ the whole process group
    })
  })

  it('escalates to SIGKILL only while the replaced child has not exited', async () => {
    // Security review H1: a child that died on SIGTERM frees its pid; the
    // escalation must key on OUR child's exit, never on "some process holds
    // this pid". A child that ignores SIGTERM gets exactly one group SIGKILL.
    await withSupervisor('sleep 30', async (companion, kill) => {
      companion.setCompanionProject('project-a')
      kill.mockClear()
      companion.setCompanionProject('project-b')
      await wait(3_400)
      expect(signals(kill, 'SIGKILL')).toEqual([])
    })
    await withSupervisor(STUBBORN, async (companion, kill) => {
      companion.setCompanionProject('project-a')
      kill.mockClear()
      await wait(300) // let python install its handler
      companion.setCompanionProject('project-b')
      const [termed] = signals(kill, 'SIGTERM')
      await wait(3_400)
      expect(signals(kill, 'SIGKILL')).toEqual([termed])
    })
  }, 15_000)

  it('never respawns the OLD configuration when the replaced child exits', async () => {
    // Code review H1: the retired child's own exit listener used to schedule a
    // backed-off restart of ITS command, spawning a second companion over the
    // new one — the very duplicate this fix removes.
    await withSupervisor('sleep 30', async (companion, kill) => {
      companion.setCompanionProject('project-a')
      companion.setCompanionProject('project-b')
      await wait(1_800) // past the exit AND the 1 s backoff step
      const alive = kill.mock.calls.filter(([pid, sig]) => sig === 0 && (pid as number) > 0)
      expect(alive).toEqual([]) // no restart path probed anything
      expect(signals(kill, 'SIGTERM')).toHaveLength(1) // one retire, no phantom child
    })
  }, 10_000)

  it('coalesces a burst of switches onto one respawn', async () => {
    await withSupervisor('sleep 30', async (companion, kill) => {
      companion.setCompanionProject('project-a')
      kill.mockClear()
      for (const p of ['b', 'c', 'd', 'e']) companion.setCompanionProject(`project-${p}`)
      // Every previous child was retired at once…
      expect(signals(kill, 'SIGTERM').length).toBeGreaterThanOrEqual(1)
      await wait(companion.REPLACE_COALESCE_MS + 200)
      // …and after the burst exactly one child is alive for project-e.
      const { execFileSync } = await import('node:child_process')
      const mine = execFileSync('/bin/ps', ['-axo', 'pid=,command='], { encoding: 'utf8' })
        .split('\n')
        .filter((l) => /sleep 30$/.test(l))
      expect(mine.length).toBeLessThanOrEqual(1)
    })
  }, 10_000)
})

describe('respawnCompanion (SOLUSDEV-329, mcp-fork-runtime.md §9)', () => {
  const signals = (kill: KillSpy, sig: string): number[] =>
    kill.mock.calls.filter(([, s]) => s === sig).map(([pid]) => pid as number)

  it('replaces the running child so newly trusted forks launch', async () => {
    await withSupervisor('sleep 30', async (companion, kill) => {
      companion.setCompanionProject('project-a')
      kill.mockClear()
      companion.respawnCompanion()
      const termed = signals(kill, 'SIGTERM')
      expect(termed).toHaveLength(1)
      expect(termed[0]).toBeLessThan(0) // the whole process group
    })
  })

  it('does nothing while no project is selected (nothing to serve)', async () => {
    await withSupervisor('sleep 30', async (companion, kill) => {
      kill.mockClear()
      companion.respawnCompanion()
      expect(signals(kill, 'SIGTERM')).toEqual([])
    })
  })
})

type KillSpy = MockInstance<typeof process.kill>

async function withSupervisor(
  cmd: string,
  body: (companion: typeof import('./companion'), kill: KillSpy) => Promise<void>
): Promise<void> {
  const realKill = process.kill.bind(process)
  const kill = vi.spyOn(process, 'kill').mockImplementation((pid, signal) => realKill(pid, signal))
  process.env.SOLUS_COMPANION_DEV_CMD = cmd
  vi.resetModules()
  try {
    const companion = await import('./companion')
    companion.startCompanion()
    try {
      await body(companion, kill)
    } finally {
      await companion.stopCompanion()
    }
  } finally {
    kill.mockRestore()
    delete process.env.SOLUS_COMPANION_DEV_CMD
  }
}
