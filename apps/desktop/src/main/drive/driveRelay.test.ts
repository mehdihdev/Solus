// SOLUSDEV-319 drive slice 3b, XPC (sol-drive.md §3 relay, §5 "Main and the
// agent"): main answers the companion's drive_request lines only for the child
// it spawned with drive on, only for identify/capture/act bound to the
// workspace main checked for that child; everything else is refused without
// reaching the agent.
import { describe, expect, it, vi } from 'vitest'
import {
  createDriveRelay,
  driveReplyLine,
  MAX_RELAY_ARGV_BYTES,
  MAX_RELAY_REPLY_BYTES,
  relayRefusal
} from './driveRelay'
import type { DriveOp, DriveTransport } from './driveTransport'

const WS = '/w/rover'
const REPLY = { ok: true, verb: 'click' }

describe('relayRefusal', () => {
  it.each([
    [['identify', '--within', WS]],
    [['capture', '--bundle', 'org.kicad.kicad', '--window', '7', '--within', WS]],
    [['act', '--within', WS, '--bundle', 'b', 'click', '--x', '1', '--y', '2']]
  ])('accepts %j', (argv) => {
    expect(relayRefusal(argv, WS)).toBeNull()
  })

  it.each([
    ['trust is not relayed', ['trust', '--within', WS]],
    ['serve is not relayed', ['serve']],
    ['no --within', ['identify']],
    ['--within twice', ['identify', '--within', WS, '--within', WS]],
    ['another workspace', ['identify', '--within', '/w/other']],
    ['a workspace inside it', ['identify', '--within', `${WS}/inner`]],
    ['--within without a value', ['identify', '--within']],
    ['--within=value form', [`identify`, `--within=${WS}`]]
  ])('refuses: %s', (_label, argv) => {
    expect(relayRefusal(argv, WS)).toEqual(expect.any(String))
  })
})

function harness(
  transport: DriveTransport | null,
  packaged = false
): {
  relay: ReturnType<typeof createDriveRelay>
  writes: Array<[object, unknown]>
} {
  const writes: Array<[object, unknown]> = []
  const relay = createDriveRelay({
    packaged,
    transport: () => transport,
    write: (child, line) => {
      expect(line.endsWith('\n')).toBe(true)
      writes.push([child, JSON.parse(line)])
    }
  })
  return { relay, writes }
}

const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0))

describe('createDriveRelay', () => {
  it('runs a valid request through the transport and writes the reply to that child', async () => {
    const request = vi.fn<DriveTransport['request']>(async () => REPLY)
    const h = harness({ request })
    const child = {}
    h.relay.attach(child, WS)
    h.relay.request(child, { id: 4, argv: ['identify', '--within', WS] })
    await flush()
    expect(request.mock.calls[0][0]).toEqual({ op: 'run', argv: ['identify', '--within', WS] })
    expect(h.writes).toEqual([[child, { type: 'drive_reply', id: 4, reply: REPLY }]])
  })

  it('a refused argv gets a usage reply and never reaches the transport', async () => {
    const request = vi.fn<DriveTransport['request']>(async () => REPLY)
    const h = harness({ request })
    const child = {}
    h.relay.attach(child, WS)
    h.relay.request(child, { id: 1, argv: ['identify', '--within', '/elsewhere'] })
    await flush()
    expect(request).not.toHaveBeenCalled()
    expect(h.writes[0][1]).toMatchObject({
      type: 'drive_reply',
      id: 1,
      reply: { ok: false, code: 'usage' }
    })
  })

  it('agent_unavailable when there is no transport or it fails', async () => {
    const none = harness(null)
    const a = {}
    none.relay.attach(a, WS)
    none.relay.request(a, { id: 1, argv: ['identify', '--within', WS] })
    const failing = harness({ request: async () => null })
    const b = {}
    failing.relay.attach(b, WS)
    failing.relay.request(b, { id: 2, argv: ['identify', '--within', WS] })
    await flush()
    for (const h of [none, failing]) {
      expect(h.writes[0][1]).toMatchObject({ reply: { ok: false, code: 'agent_unavailable' } })
    }
  })

  it('ignores a child spawned without drive, and any child that is not current', async () => {
    const request = vi.fn<DriveTransport['request']>(async () => REPLY)
    const h = harness({ request })
    const noDrive = {}
    h.relay.attach(noDrive, null)
    h.relay.request(noDrive, { id: 1, argv: ['identify', '--within', WS] })
    const old = {}
    h.relay.attach(old, WS)
    h.relay.attach({}, WS) // replaced
    h.relay.request(old, { id: 2, argv: ['identify', '--within', WS] })
    await flush()
    expect(request).not.toHaveBeenCalled()
    expect(h.writes).toEqual([])
  })
})

describe('createDriveRelay — cancellation', () => {
  it('drive_cancel aborts the call in flight, and nothing is written for it', async () => {
    let seen: AbortSignal | null = null
    const request = vi.fn(async (_op: DriveOp, signal: AbortSignal) => {
      seen = signal
      await new Promise((r) => signal.addEventListener('abort', r))
      return null
    })
    const h = harness({ request })
    const child = {}
    h.relay.attach(child, WS)
    h.relay.request(child, { id: 9, argv: ['act', '--within', WS] })
    h.relay.cancel(child, 9)
    await flush()
    expect(seen!.aborted).toBe(true)
    expect(h.writes).toEqual([])
  })

  it('detach (exit or replace) aborts every call in flight', async () => {
    const signals: AbortSignal[] = []
    const h = harness({
      request: async (_op, signal) => {
        signals.push(signal)
        return new Promise(() => undefined)
      }
    })
    const child = {}
    h.relay.attach(child, WS)
    h.relay.request(child, { id: 1, argv: ['identify', '--within', WS] })
    await flush()
    h.relay.detach(child)
    expect(signals.map((s) => s.aborted)).toEqual([true])
  })

  it('one call at a time per child (LOW-4): a second concurrent request gets usage', async () => {
    const h = harness({ request: () => new Promise(() => undefined) })
    const child = {}
    h.relay.attach(child, WS)
    h.relay.request(child, { id: 1, argv: ['identify', '--within', WS] })
    h.relay.request(child, { id: 2, argv: ['capture', '--within', WS] })
    h.relay.request(child, { id: 1, argv: ['identify', '--within', WS] })
    await flush()
    expect(h.writes).toEqual([
      [
        child,
        {
          type: 'drive_reply',
          id: 2,
          reply: { ok: false, code: 'usage', message: 'one drive call at a time' }
        }
      ],
      [
        child,
        {
          type: 'drive_reply',
          id: 1,
          reply: { ok: false, code: 'usage', message: 'one drive call at a time' }
        }
      ]
    ])
  })
})

describe('createDriveRelay — limits and the bundle gate', () => {
  it('argv over the byte cap is refused before the transport (L3: the XPC request stays < 64 KiB)', async () => {
    const request = vi.fn<DriveTransport['request']>(async () => REPLY)
    const h = harness({ request })
    const child = {}
    h.relay.attach(child, WS)
    const text = 'x'.repeat(MAX_RELAY_ARGV_BYTES)
    h.relay.request(child, { id: 1, argv: ['act', '--within', WS, 'type', '--text', text] })
    await flush()
    expect(request).not.toHaveBeenCalled()
    expect(h.writes[0][1]).toMatchObject({ reply: { ok: false, code: 'usage' } })
    expect(MAX_RELAY_ARGV_BYTES).toBeLessThanOrEqual(60 * 1024)
  })

  it('a reply over 24 MiB as JSON becomes helper_output (L4)', async () => {
    const huge = { ok: true, png: 'A'.repeat(MAX_RELAY_REPLY_BYTES) }
    const h = harness({ request: async () => huge })
    const child = {}
    h.relay.attach(child, WS)
    h.relay.request(child, { id: 3, argv: ['capture', '--within', WS] })
    await flush()
    expect(h.writes[0][1]).toMatchObject({ id: 3, reply: { ok: false, code: 'helper_output' } })
  })

  it('waits for the spawn-time bundle check; a failed check never reaches the agent (HIGH-1)', async () => {
    const request = vi.fn<DriveTransport['request']>(async () => REPLY)
    const h = harness({ request })
    const child = {}
    let pass: (ok: boolean) => void = () => undefined
    h.relay.attach(child, WS, new Promise<boolean>((r) => (pass = r)))
    h.relay.request(child, { id: 1, argv: ['identify', '--within', WS] })
    await flush()
    expect(request).not.toHaveBeenCalled()
    pass(false)
    await flush()
    expect(request).not.toHaveBeenCalled()
    expect(h.writes[0][1]).toMatchObject({ reply: { ok: false, code: 'agent_unavailable' } })
  })

  it('LOW-A: packaged with no bundle check given fails closed — nothing reaches the agent', async () => {
    const request = vi.fn<DriveTransport['request']>(async () => REPLY)
    const h = harness({ request }, true)
    const child = {}
    h.relay.attach(child, WS)
    h.relay.request(child, { id: 1, argv: ['identify', '--within', WS] })
    await flush()
    expect(request).not.toHaveBeenCalled()
    expect(h.writes[0][1]).toMatchObject({ reply: { ok: false, code: 'agent_unavailable' } })
  })

  it('an interrupted act (the transport rejects) is agent_unavailable', async () => {
    const h = harness({ request: () => Promise.reject(new Error('interrupted')) })
    const child = {}
    h.relay.attach(child, WS)
    h.relay.request(child, {
      id: 1,
      argv: ['act', '--within', WS, 'click', '--x', '1', '--y', '1']
    })
    await flush()
    expect(h.writes[0][1]).toMatchObject({ reply: { ok: false, code: 'agent_unavailable' } })
  })

  it('a passed bundle check lets the call through', async () => {
    const request = vi.fn<DriveTransport['request']>(async () => REPLY)
    const h = harness({ request })
    const child = {}
    h.relay.attach(child, WS, Promise.resolve(true))
    h.relay.request(child, { id: 1, argv: ['identify', '--within', WS] })
    await flush()
    expect(h.writes[0][1]).toEqual({ type: 'drive_reply', id: 1, reply: REPLY })
  })
})

it('driveReplyLine is one newline-terminated frame', () => {
  expect(driveReplyLine(3, { ok: true })).toBe(
    '{"type":"drive_reply","id":3,"reply":{"ok":true}}\n'
  )
})

it('every reply line starts with {"type":"drive_reply", — the companion admits an oversize stdin line only on that prefix', async () => {
  const capture = { ok: true, png: 'A'.repeat(1024 * 1024), imageWidth: 2048 }
  expect(driveReplyLine(1, capture).startsWith('{"type":"drive_reply",')).toBe(true)
  const lines: string[] = []
  const relay = createDriveRelay({
    packaged: false,
    transport: () => ({ request: async () => capture }),
    write: (_child, line) => void lines.push(line)
  })
  const child = {}
  relay.attach(child, WS)
  relay.request(child, { id: 5, argv: ['capture', '--within', WS] })
  relay.request(child, { id: 6, argv: ['serve'] }) // refusals too
  await new Promise((r) => setTimeout(r, 0))
  expect(lines).toHaveLength(2)
  for (const line of lines) expect(line.startsWith('{"type":"drive_reply",')).toBe(true)
})
