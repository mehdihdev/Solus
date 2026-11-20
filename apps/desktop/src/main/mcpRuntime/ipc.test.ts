// SOLUSDEV-329 — the mcpRuntime:* IPC handlers
// (docs/architecture/mcp-fork-runtime.md §9): sender-gated, input-validated,
// one provisioning run at a time, progress to the requester only, and a
// companion respawn after a provision that made at least one fork ready.
import { EventEmitter } from 'node:events'
import { PassThrough } from 'node:stream'
import { describe, expect, it, vi } from 'vitest'
import { MCP_RUNTIME_CHANNELS } from './channels'
import { createMcpRuntimeIpc, registerMcpRuntimeIpc, type McpRuntimeIpcDeps } from './ipc'
import type { RuntimeChild } from './runtimeCli'
import type { RuntimeChoice } from './runtimeSettings'

class FakeChild extends EventEmitter implements RuntimeChild {
  stdout = new PassThrough()
  stderr = new PassThrough()
  pid = 77
  emitLines(...objs: Record<string, unknown>[]): void {
    for (const o of objs) this.stdout.write(`${JSON.stringify({ v: 1, ...o })}\n`)
  }
  async close(code: number): Promise<void> {
    this.stdout.end()
    await new Promise((r) => setImmediate(r))
    this.emit('close', code)
  }
}

interface Sender {
  send: ReturnType<typeof vi.fn>
  isDestroyed: () => boolean
}

function setup(over: Partial<McpRuntimeIpcDeps> = {}): {
  deps: McpRuntimeIpcDeps
  children: FakeChild[]
  ipc: ReturnType<typeof createMcpRuntimeIpc>
  ev: { sender: Sender }
  saved: RuntimeChoice[]
} {
  const children: FakeChild[] = []
  const saved: RuntimeChoice[] = []
  const deps: McpRuntimeIpcDeps = {
    isAllowed: (event) => (event as { sender: unknown }).sender === ev.sender,
    commandLine: () => ({ command: '/app/solus-companion', args: [] }),
    env: () => ({ PATH: '/usr/bin' }),
    run: {
      spawn: vi.fn(() => {
        const c = new FakeChild()
        children.push(c)
        return c
      }),
      kill: vi.fn()
    },
    settings: {
      read: () => ({ mode: 'path', path: '/usr/bin/python3.12', writable: true }),
      write: (choice) => {
        saved.push(choice)
        return true
      }
    },
    probe: vi.fn(async () => ({ ok: true as const, version: '3.12.7', minor: '3.12' as const })),
    pickInterpreter: vi.fn(async () => '/picked/python3.13'),
    realpath: (p: string) => p,
    confirmManagedDownload: vi.fn(async () => true),
    respawnCompanion: vi.fn(),
    newRunId: (() => {
      let n = 0
      return () => `run-${++n}`
    })(),
    ...over
  }
  const ev = { sender: { send: vi.fn(), isDestroyed: () => false } }
  return { deps, children, ipc: createMcpRuntimeIpc(deps), ev, saved }
}

const flush = (): Promise<void> => new Promise((r) => setImmediate(r))
const DONE = (ok: number, failed = 0): Record<string, unknown> => ({
  type: 'done',
  outcome: failed ? 'partial' : 'ok',
  ok,
  failed,
  skipped: 0
})
const candidate = (path: string, supported = true): Record<string, unknown> => ({
  type: 'candidate',
  path,
  version: supported ? '3.12.7' : '3.11.9',
  implementation: 'cpython',
  source: 'path',
  supported,
  reason: supported ? null : 'python_unsupported_version'
})

/** Runs `detect` to completion with the given candidate lines. */
async function detectWith(
  t: ReturnType<typeof setup>,
  ...lines: Record<string, unknown>[]
): Promise<void> {
  const p = t.ipc.detect(t.ev)
  await flush()
  t.children.at(-1)!.emitLines(...lines, DONE(lines.length))
  await t.children.at(-1)!.close(0)
  await p
}

const foreign = { sender: { send: vi.fn(), isDestroyed: () => false } }

describe('sender gate', () => {
  it('refuses every channel from a foreign sender and spawns nothing', async () => {
    const { ipc, deps } = setup()
    await expect(ipc.detect(foreign)).rejects.toThrow('unauthorized sender')
    await expect(ipc.status(foreign)).rejects.toThrow('unauthorized sender')
    await expect(ipc.getChoice(foreign)).rejects.toThrow('unauthorized sender')
    await expect(ipc.choose(foreign, { mode: 'managed' })).rejects.toThrow('unauthorized sender')
    await expect(ipc.provision(foreign, { trigger: 'settings' })).rejects.toThrow(
      'unauthorized sender'
    )
    await expect(ipc.installManaged(foreign, { consent: true })).rejects.toThrow(
      'unauthorized sender'
    )
    await expect(ipc.cancel(foreign, { runId: 'run-1' })).rejects.toThrow('unauthorized sender')
    expect(deps.run.spawn).not.toHaveBeenCalled()
  })
})

describe('registerMcpRuntimeIpc', () => {
  it('registers exactly the §9 invoke channels', () => {
    const handle = vi.fn()
    registerMcpRuntimeIpc({ handle }, setup().ipc)
    const invoke = Object.values(MCP_RUNTIME_CHANNELS).filter(
      (c) => c !== MCP_RUNTIME_CHANNELS.progress
    )
    expect(handle.mock.calls.map(([c]) => c).sort()).toEqual(invoke.sort())
  })
})

describe('detect / status', () => {
  it('detect returns the validated candidates', async () => {
    const { ipc, children, ev } = setup()
    const p = ipc.detect(ev)
    await flush()
    children[0].emitLines(
      {
        type: 'candidate',
        path: '/usr/bin/python3.12',
        version: '3.12.7',
        implementation: 'cpython',
        source: 'path',
        supported: true,
        reason: null
      },
      DONE(1)
    )
    await children[0].close(0)
    await expect(p).resolves.toEqual({
      candidates: [expect.objectContaining({ path: '/usr/bin/python3.12', supported: true })]
    })
  })

  it('status runs `runtime status` and returns the forks', async () => {
    const { ipc, children, ev, deps } = setup()
    const p = ipc.status(ev)
    await flush()
    expect(vi.mocked(deps.run.spawn).mock.calls[0][1]).toEqual(['runtime', 'status'])
    children[0].emitLines(
      {
        type: 'status',
        fork: 'kicad',
        state: 'needs_setup',
        detail: 'needs_setup:no_env',
        base_version: null,
        managed: false
      },
      DONE(0)
    )
    await children[0].close(0)
    await expect(p).resolves.toEqual({ forks: [expect.objectContaining({ fork: 'kicad' })] })
  })

  it('rejects when the companion command is unavailable', async () => {
    const { ipc, ev } = setup({ commandLine: () => null })
    await expect(ipc.detect(ev)).rejects.toThrow('unavailable')
  })
})

describe('getChoice / choose', () => {
  it('getChoice returns the saved choice', async () => {
    const { ipc, ev } = setup()
    await expect(ipc.getChoice(ev)).resolves.toEqual({
      mode: 'path',
      path: '/usr/bin/python3.12',
      writable: true
    })
  })

  it('a detected supported path is re-probed in main before it is saved', async () => {
    const t = setup()
    const { ipc, ev, deps, saved } = t
    await detectWith(t, candidate('/usr/bin/python3.12'))
    await expect(ipc.choose(ev, { mode: 'path', path: '/usr/bin/python3.12' })).resolves.toEqual({
      ok: true,
      version_minor: '3.12'
    })
    expect(deps.probe).toHaveBeenCalledWith('/usr/bin/python3.12')
    expect(saved).toEqual([{ mode: 'path', path: '/usr/bin/python3.12' }])
  })

  it("a detected path that fails main's re-probe is not saved", async () => {
    const t = setup({
      probe: async () => ({ ok: false, error_code: 'python_unsupported_version' })
    })
    const { ipc, ev, saved } = t
    await detectWith(t, candidate('/usr/bin/python3'))
    await expect(ipc.choose(ev, { mode: 'path', path: '/usr/bin/python3' })).resolves.toEqual({
      ok: false,
      error_code: 'python_unsupported_version'
    })
    expect(saved).toEqual([])
  })

  it('a non-absolute or malformed path is refused without probing', async () => {
    const { ipc, ev, deps, saved } = setup()
    for (const bad of [{ mode: 'path', path: 'python3' }, { mode: 'nope' }, null, 'x']) {
      await expect(ipc.choose(ev, bad)).resolves.toMatchObject({ ok: false })
    }
    expect(deps.probe).not.toHaveBeenCalled()
    expect(saved).toEqual([])
  })

  it('an arbitrary absolute path not in the detect results is refused and never run', async () => {
    const t = setup()
    const { ipc, ev, deps, saved } = t
    await detectWith(t, candidate('/usr/bin/python3.12'))
    const spawned = vi.mocked(deps.run.spawn).mock.calls.length
    await expect(ipc.choose(ev, { mode: 'path', path: '/tmp/evil' })).resolves.toEqual({
      ok: false,
      error_code: 'python_not_found'
    })
    expect(deps.probe).not.toHaveBeenCalled()
    expect(deps.pickInterpreter).not.toHaveBeenCalled()
    expect(vi.mocked(deps.run.spawn).mock.calls.length).toBe(spawned)
    expect(saved).toEqual([])
  })

  it('a path is refused before any detect has run', async () => {
    const { ipc, ev, deps } = setup()
    await expect(ipc.choose(ev, { mode: 'path', path: '/usr/bin/python3.12' })).resolves.toEqual({
      ok: false,
      error_code: 'python_not_found'
    })
    expect(deps.probe).not.toHaveBeenCalled()
  })

  it('a detected but unsupported candidate is refused without probing', async () => {
    const t = setup()
    await detectWith(t, candidate('/usr/bin/python3.11', false))
    await expect(
      t.ipc.choose(t.ev, { mode: 'path', path: '/usr/bin/python3.11' })
    ).resolves.toMatchObject({ ok: false })
    expect(t.deps.probe).not.toHaveBeenCalled()
  })

  it('matches detected candidates by realpath', async () => {
    const links: Record<string, string> = {
      '/usr/local/bin/python3': '/opt/py/bin/python3.12',
      '/opt/py/bin/python3.12': '/opt/py/bin/python3.12'
    }
    const t = setup({ realpath: (p) => links[p] ?? null })
    await detectWith(t, candidate('/opt/py/bin/python3.12'))
    await expect(
      t.ipc.choose(t.ev, { mode: 'path', path: '/usr/local/bin/python3' })
    ).resolves.toMatchObject({ ok: true })
    await expect(t.ipc.choose(t.ev, { mode: 'path', path: '/missing' })).resolves.toMatchObject({
      ok: false
    })
  })

  it('a newer detect replaces the accepted candidates', async () => {
    const t = setup()
    await detectWith(t, candidate('/usr/bin/python3.12'))
    await detectWith(t, candidate('/usr/bin/python3.13'))
    await expect(
      t.ipc.choose(t.ev, { mode: 'path', path: '/usr/bin/python3.12' })
    ).resolves.toMatchObject({ ok: false, error_code: 'python_not_found' })
  })

  it('mode path without a path opens the picker, then probes the pick', async () => {
    const { ipc, ev, deps, saved } = setup({
      probe: vi.fn(async () => ({ ok: true as const, version: '3.13.1', minor: '3.13' as const }))
    })
    await expect(ipc.choose(ev, { mode: 'path' })).resolves.toEqual({
      ok: true,
      version_minor: '3.13'
    })
    expect(deps.pickInterpreter).toHaveBeenCalled()
    expect(saved).toEqual([{ mode: 'path', path: '/picked/python3.13' }])
  })

  it('a cancelled picker saves nothing', async () => {
    const { ipc, ev, saved } = setup({ pickInterpreter: async () => null })
    await expect(ipc.choose(ev, { mode: 'path' })).resolves.toEqual({
      ok: false,
      error_code: 'cancelled'
    })
    expect(saved).toEqual([])
  })

  it('managed and auto save without a probe', async () => {
    const { ipc, ev, deps, saved } = setup()
    await expect(ipc.choose(ev, { mode: 'managed' })).resolves.toEqual({
      ok: true,
      version_minor: '3.12'
    })
    await expect(ipc.choose(ev, { mode: 'auto' })).resolves.toEqual({
      ok: true,
      version_minor: null
    })
    expect(deps.probe).not.toHaveBeenCalled()
    expect(saved).toEqual([
      { mode: 'managed', path: null },
      { mode: 'auto', path: null }
    ])
  })

  it('a read-only config refuses the choice', async () => {
    const { ipc, ev } = setup({
      settings: { read: () => ({ mode: 'auto', path: null, writable: false }), write: () => false }
    })
    await expect(ipc.choose(ev, { mode: 'managed' })).resolves.toEqual({
      ok: false,
      error_code: 'internal'
    })
  })
})

describe('provision', () => {
  it('passes the saved interpreter and forks as argv and pushes progress to the requester only', async () => {
    const { ipc, ev, children, deps } = setup()
    const other = { send: vi.fn(), isDestroyed: () => false }
    await expect(ipc.provision(ev, { trigger: 'repair', forks: ['local'] })).resolves.toEqual({
      runId: 'run-1'
    })
    expect(vi.mocked(deps.run.spawn).mock.calls[0][1]).toEqual([
      'runtime',
      'provision',
      '--fork',
      'local',
      '--python',
      '/usr/bin/python3.12'
    ])
    children[0].emitLines({ type: 'progress', fork: 'local', step: 'venv', done: 0, total: null })
    await flush()
    expect(ev.sender.send).toHaveBeenCalledWith(MCP_RUNTIME_CHANNELS.progress, {
      runId: 'run-1',
      event: { type: 'progress', fork: 'local', step: 'venv', done: 0, total: null }
    })
    expect(other.send).not.toHaveBeenCalled()
  })

  it('respawns the companion after a done with ok > 0', async () => {
    const { ipc, ev, children, deps } = setup()
    await ipc.provision(ev, { trigger: 'settings' })
    children[0].emitLines(DONE(1, 1))
    await children[0].close(1)
    await flush()
    expect(deps.respawnCompanion).toHaveBeenCalledTimes(1)
  })

  it('does not respawn after a failed provision', async () => {
    const { ipc, ev, children, deps } = setup()
    await ipc.provision(ev, { trigger: 'settings' })
    children[0].emitLines({ type: 'done', outcome: 'failed', ok: 0, failed: 2, skipped: 0 })
    await children[0].close(2)
    await flush()
    expect(deps.respawnCompanion).not.toHaveBeenCalled()
  })

  it('a second run while one is active rejects busy', async () => {
    const { ipc, ev, children } = setup()
    await ipc.provision(ev, { trigger: 'settings' })
    await expect(ipc.provision(ev, { trigger: 'settings' })).rejects.toThrow('busy')
    await expect(ipc.installManaged(ev, { consent: true })).rejects.toThrow('busy')
    children[0].emitLines(DONE(1))
    await children[0].close(0)
    await flush()
    await expect(ipc.provision(ev, { trigger: 'settings' })).resolves.toEqual({ runId: 'run-2' })
  })

  it.each([
    [{ trigger: 'cron' }],
    [{ trigger: 'settings', forks: ['../etc'] }],
    [{ trigger: 'settings', forks: 'kicad' }],
    [{ trigger: 'settings', forks: Array.from({ length: 33 }, (_, i) => `f${i}`) }],
    [null]
  ])('refuses bad input %j', async (input) => {
    const { ipc, ev, deps } = setup()
    await expect(ipc.provision(ev, input)).rejects.toThrow('invalid request')
    expect(deps.run.spawn).not.toHaveBeenCalled()
  })

  it('does not push to a destroyed sender', async () => {
    const { ipc, ev, children } = setup()
    ev.sender.isDestroyed = () => true
    await ipc.provision(ev, { trigger: 'settings' })
    children[0].emitLines(DONE(0))
    await flush()
    expect(ev.sender.send).not.toHaveBeenCalled()
  })
})

describe('installManaged', () => {
  it('requires the literal consent: true', async () => {
    const { ipc, ev, deps } = setup()
    for (const bad of [{}, { consent: 'yes' }, { consent: 1 }, null]) {
      await expect(ipc.installManaged(ev, bad)).rejects.toThrow('consent required')
    }
    expect(deps.run.spawn).not.toHaveBeenCalled()
  })

  it("main's own confirmation is asked before the download, and a cancel runs nothing", async () => {
    const { ipc, ev, deps } = setup({ confirmManagedDownload: vi.fn(async () => false) })
    await expect(ipc.installManaged(ev, { consent: true })).resolves.toEqual({
      runId: null,
      error_code: 'cancelled'
    })
    expect(deps.confirmManagedDownload).toHaveBeenCalledTimes(1)
    expect(deps.run.spawn).not.toHaveBeenCalled()
  })

  it('a failed confirmation dialog runs nothing', async () => {
    const { ipc, ev, deps } = setup({
      confirmManagedDownload: vi.fn(async () => Promise.reject(new Error('no window')))
    })
    await expect(ipc.installManaged(ev, { consent: true })).resolves.toEqual({
      runId: null,
      error_code: 'cancelled'
    })
    expect(deps.run.spawn).not.toHaveBeenCalled()
  })

  it('does not ask for confirmation without the renderer consent', async () => {
    const { ipc, ev, deps } = setup()
    await expect(ipc.installManaged(ev, {})).rejects.toThrow('consent required')
    expect(deps.confirmManagedDownload).not.toHaveBeenCalled()
  })

  it('runs `runtime install-managed` and never respawns', async () => {
    const { ipc, ev, deps, children } = setup()
    await expect(ipc.installManaged(ev, { consent: true })).resolves.toEqual({ runId: 'run-1' })
    expect(vi.mocked(deps.run.spawn).mock.calls[0][1]).toEqual(['runtime', 'install-managed'])
    children[0].emitLines(DONE(1))
    await children[0].close(0)
    await flush()
    expect(deps.respawnCompanion).not.toHaveBeenCalled()
  })
})

describe('cancel', () => {
  it('cancels the active run by id and kills its child', async () => {
    const { ipc, ev, deps } = setup()
    const { runId } = await ipc.provision(ev, { trigger: 'settings' })
    await expect(ipc.cancel(ev, { runId: 'other' })).resolves.toEqual({ ok: false })
    await expect(ipc.cancel(ev, { runId })).resolves.toEqual({ ok: true })
    expect(deps.run.kill).toHaveBeenCalledWith(77, 'SIGTERM')
  })

  it('refuses a malformed request', async () => {
    const { ipc, ev } = setup()
    await expect(ipc.cancel(ev, { runId: 5 })).resolves.toEqual({ ok: false })
  })
})
