// SOLUSDEV-319 drive slice 3b, XPC (sol-drive.md §2.1, §5 "Main and the
// agent"): main is the agent's only client. Packaged: the native XPC module;
// dev: the debug helper run once per call. Both answer one reply object or null.
import { EventEmitter } from 'node:events'
import { describe, expect, it, vi } from 'vitest'
import {
  DEV_STDERR_LOG_BYTES,
  DEV_STDOUT_CAP_BYTES,
  DRIVE_KILL_GRACE_MS,
  createDevTransport,
  createXpcTransport,
  loadXpcModule,
  parseReplyObject,
  type DevSpawn,
  type XpcModule
} from './driveTransport'

const REPLY = { ok: true, verb: 'click' }

describe('parseReplyObject', () => {
  it('exactly one JSON object', () => {
    expect(parseReplyObject(`${JSON.stringify(REPLY)}\n`)).toEqual(REPLY)
  })
  it.each([[''], ['x'], ['[1]'], ['{"a":1}\n{"b":2}'], ['null']])('null for %j', (raw) => {
    expect(parseReplyObject(raw)).toBeNull()
  })
})

describe('createXpcTransport', () => {
  function xpc(answer: () => Promise<string>): XpcModule & {
    request: ReturnType<typeof vi.fn>
    cancel: ReturnType<typeof vi.fn>
  } {
    return { request: vi.fn(answer), cancel: vi.fn() }
  }

  it('sends a v1 request with the op and parses the reply', async () => {
    const m = xpc(async () => JSON.stringify(REPLY))
    const t = createXpcTransport(m)
    expect(
      await t.request(
        { op: 'run', argv: ['identify', '--within', '/w'] },
        new AbortController().signal
      )
    ).toEqual(REPLY)
    const [json, timeout] = m.request.mock.calls[0]
    expect(JSON.parse(json as string)).toEqual({
      v: 1,
      op: 'run',
      argv: ['identify', '--within', '/w']
    })
    expect(timeout).toBeGreaterThan(0)
    await t.request({ op: 'trust', prompt: true }, new AbortController().signal)
    expect(JSON.parse(m.request.mock.calls[1][0] as string)).toEqual({
      v: 1,
      op: 'trust',
      prompt: true
    })
  })

  it('null on a rejected request or a malformed reply', async () => {
    const signal = new AbortController().signal
    expect(
      await createXpcTransport(xpc(async () => Promise.reject(new Error('invalid')))).request(
        { op: 'trust', prompt: false },
        signal
      )
    ).toBeNull()
    expect(
      await createXpcTransport(xpc(async () => 'nope')).request(
        { op: 'trust', prompt: false },
        signal
      )
    ).toBeNull()
  })

  it('abort cancels the call in the agent and answers null', async () => {
    let resolve: (v: string) => void = () => undefined
    const m = xpc(() => new Promise<string>((r) => (resolve = r)))
    const ac = new AbortController()
    const pending = createXpcTransport(m).request({ op: 'run', argv: ['act'] }, ac.signal)
    ac.abort()
    resolve(JSON.stringify(REPLY))
    expect(await pending).toBeNull()
    expect(m.cancel).toHaveBeenCalledTimes(1)
  })

  it('an already-aborted signal sends nothing', async () => {
    const m = xpc(async () => '{}')
    const ac = new AbortController()
    ac.abort()
    expect(
      await createXpcTransport(m).request({ op: 'trust', prompt: false }, ac.signal)
    ).toBeNull()
    expect(m.request).not.toHaveBeenCalled()
  })
})

describe('loadXpcModule', () => {
  it('returns the module when it exports request and cancel', () => {
    const m = { request: async () => '', cancel: () => undefined }
    expect(loadXpcModule(() => m)).toBe(m)
  })
  it('null when loading throws or the shape is wrong', () => {
    const warn = vi.fn()
    expect(
      loadXpcModule(() => {
        throw new Error('dlopen failed')
      }, warn)
    ).toBeNull()
    expect(loadXpcModule(() => ({ request: 1 }), warn)).toBeNull()
    expect(warn).toHaveBeenCalledTimes(2)
  })
})

class FakeChild extends EventEmitter {
  stdout = new EventEmitter()
  stderr = new EventEmitter()
  signals: string[] = []
  kill(signal: string): boolean {
    this.signals.push(signal)
    return true
  }
}

function dev(helper: string | null = '/dbg/solus-input'): {
  spawn: ReturnType<typeof vi.fn> & DevSpawn
  child: () => FakeChild
  warn: ReturnType<typeof vi.fn>
  timers: Array<{ cb: () => void; ms: number }>
  transport: ReturnType<typeof createDevTransport>
} {
  const children: FakeChild[] = []
  const timers: Array<{ cb: () => void; ms: number }> = []
  const spawn = vi.fn(() => {
    const c = new FakeChild()
    children.push(c)
    return c
  }) as unknown as ReturnType<typeof vi.fn> & DevSpawn
  const warn = vi.fn()
  const transport = createDevTransport({
    helper: () => helper,
    spawn,
    warn,
    setTimeout: (cb, ms) => {
      timers.push({ cb, ms })
      return timers.length
    },
    clearTimeout: () => undefined
  })
  return { spawn, child: () => children[children.length - 1], warn, timers, transport }
}

describe('createDevTransport', () => {
  it('runs the helper once with the argv: argument list, PATH-only env, no shell', async () => {
    const d = dev()
    const pending = d.transport.request(
      { op: 'run', argv: ['identify', '--within', '/w'] },
      new AbortController().signal
    )
    expect(d.spawn).toHaveBeenCalledWith('/dbg/solus-input', ['identify', '--within', '/w'], {
      env: { PATH: '/usr/bin:/bin' },
      stdio: ['ignore', 'pipe', 'pipe'],
      shell: false
    })
    d.child().stdout.emit('data', Buffer.from(JSON.stringify(REPLY)))
    d.child().emit('close', 1, null) // a refusal exits non-zero but still answers
    expect(await pending).toEqual(REPLY)
  })

  it('trust maps to `trust [--prompt]`', async () => {
    const d = dev()
    void d.transport.request({ op: 'trust', prompt: true }, new AbortController().signal)
    expect(d.spawn.mock.calls[0][1]).toEqual(['trust', '--prompt'])
    void d.transport.request({ op: 'trust', prompt: false }, new AbortController().signal)
    expect(d.spawn.mock.calls[1][1]).toEqual(['trust'])
  })

  it('logs stderr, bounded', async () => {
    const d = dev()
    const pending = d.transport.request(
      { op: 'trust', prompt: false },
      new AbortController().signal
    )
    d.child().stderr.emit('data', Buffer.from('e'.repeat(DEV_STDERR_LOG_BYTES * 3)))
    d.child().emit('close', 1, null)
    expect(await pending).toBeNull()
    expect(d.warn).toHaveBeenCalledTimes(1)
    expect((d.warn.mock.calls[0][0] as string).length).toBeLessThan(DEV_STDERR_LOG_BYTES + 64)
  })

  it('abort → SIGTERM, then SIGKILL after the grace, and null', async () => {
    const d = dev()
    const ac = new AbortController()
    const pending = d.transport.request({ op: 'run', argv: ['act'] }, ac.signal)
    ac.abort()
    expect(d.child().signals).toEqual(['SIGTERM'])
    const grace = d.timers.find((t) => t.ms === DRIVE_KILL_GRACE_MS)
    grace?.cb()
    expect(d.child().signals).toEqual(['SIGTERM', 'SIGKILL'])
    d.child().stdout.emit('data', Buffer.from(JSON.stringify(REPLY)))
    d.child().emit('close', null, 'SIGKILL')
    expect(await pending).toBeNull()
  })
})

describe('createDevTransport — kills and failures', () => {
  it('the deadline kills it the same way', async () => {
    const d = dev()
    const pending = d.transport.request({ op: 'run', argv: ['act'] }, new AbortController().signal)
    d.timers[0].cb() // the deadline
    expect(d.child().signals).toEqual(['SIGTERM'])
    d.child().emit('close', null, 'SIGTERM')
    expect(await pending).toBeNull()
  })

  it('stdout over the cap kills it and answers null', async () => {
    const d = dev()
    const pending = d.transport.request(
      { op: 'run', argv: ['capture'] },
      new AbortController().signal
    )
    d.child().stdout.emit('data', Buffer.alloc(DEV_STDOUT_CAP_BYTES + 1, 0x41))
    expect(d.child().signals).toEqual(['SIGTERM'])
    d.child().emit('close', null, 'SIGTERM')
    expect(await pending).toBeNull()
  })

  it('null without a helper, on a spawn error, or a throwing spawn', async () => {
    const signal = new AbortController().signal
    expect(await dev(null).transport.request({ op: 'trust', prompt: false }, signal)).toBeNull()
    const d = dev()
    const pending = d.transport.request({ op: 'trust', prompt: false }, signal)
    d.child().emit('error', new Error('ENOENT'))
    expect(await pending).toBeNull()
    d.spawn.mockImplementationOnce(() => {
      throw new Error('EACCES')
    })
    expect(await d.transport.request({ op: 'trust', prompt: false }, signal)).toBeNull()
  })
})
