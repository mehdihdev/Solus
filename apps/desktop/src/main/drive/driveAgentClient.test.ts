// SOLUSDEV-319 drive slice 3b (sol-drive.md §2.1 wire protocol v1): main's
// agent client — one request per connection, one line back, one deadline, a
// reply cap; replies are untrusted until parsed.
import { createServer, type Server } from 'node:net'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import {
  AGENT_MAX_REPLY_BYTES,
  agentRequest,
  parseSessionReply,
  requestAgentSession,
  requestAgentTrust
} from './driveAgentClient'

const TOKEN = 'A'.repeat(43)

let dir: string | null = null
let server: Server | null = null
afterEach(async () => {
  await new Promise<void>((r) => (server ? server.close(() => r()) : r()))
  server = null
  if (dir) rmSync(dir, { recursive: true, force: true })
  dir = null
})

/** A real unix-socket agent that answers `reply(requestLine)` (or nothing). */
async function agent(reply: (line: string) => string | null, seen: string[] = []): Promise<string> {
  dir = mkdtempSync(join(tmpdir(), 'sd-'))
  const socket = join(dir, 'a.sock')
  server = createServer((conn) => {
    let buf = ''
    conn.on('data', (chunk) => {
      buf += chunk.toString('utf8')
      const nl = buf.indexOf('\n')
      if (nl < 0) return
      const line = buf.slice(0, nl)
      seen.push(line)
      const answer = reply(line)
      if (answer !== null) conn.end(answer)
    })
    conn.on('error', () => undefined)
  })
  await new Promise<void>((r) => server!.listen(socket, () => r()))
  return socket
}

describe('agentRequest', () => {
  it('sends one newline-terminated JSON line and parses the one line back', async () => {
    const seen: string[] = []
    const socket = await agent(() => '{"ok":true,"x":1}\n', seen)
    expect(await agentRequest(socket, { v: 1, op: 'trust', prompt: false })).toEqual({
      ok: true,
      x: 1
    })
    expect(seen).toEqual(['{"v":1,"op":"trust","prompt":false}'])
  })

  it('null when nothing listens', async () => {
    expect(await agentRequest('/nonexistent/solus/agent.sock', { v: 1 })).toBeNull()
  })

  it('null at the deadline when the agent never answers', async () => {
    const socket = await agent(() => null)
    expect(await agentRequest(socket, { v: 1 }, { deadlineMs: 50 })).toBeNull()
  })

  it('null for a reply over the cap, or for non-JSON / two lines', async () => {
    const big = await agent(() => `"${'x'.repeat(AGENT_MAX_REPLY_BYTES)}"\n`)
    expect(await agentRequest(big, { v: 1 })).toBeNull()
  })

  it.each([['not json\n'], ['{"ok":true}\n{"ok":true}\n'], ['[1]\n']])(
    'null for a malformed reply %#',
    async (raw) => {
      const socket = await agent(() => raw)
      expect(await agentRequest(socket, { v: 1 })).toBeNull()
    }
  )
})

describe('session and trust ops', () => {
  it('session: the 43-character base64url token', async () => {
    const seen: string[] = []
    const socket = await agent(() => JSON.stringify({ ok: true, token: TOKEN }) + '\n', seen)
    expect(await requestAgentSession(socket)).toBe(TOKEN)
    expect(seen).toEqual(['{"v":1,"op":"session"}'])
  })

  it('trust: the slice 3 reply shape, prompt passed through', async () => {
    const seen: string[] = []
    const socket = await agent(
      () =>
        JSON.stringify({ ok: true, trust: { accessibility: true, screenRecording: false } }) + '\n',
      seen
    )
    expect(await requestAgentTrust(socket, true)).toEqual({
      trust: { accessibility: true, screenRecording: false },
      unsignedDev: false
    })
    expect(seen).toEqual(['{"v":1,"op":"trust","prompt":true}'])
  })

  it('trust: null on a refusal', async () => {
    const socket = await agent(() => '{"ok":false,"code":"caller_untrusted"}\n')
    expect(await requestAgentTrust(socket, false)).toBeNull()
  })
})

describe('parseSessionReply', () => {
  it.each([
    ['ok false', { ok: false, token: TOKEN }],
    ['short token', { ok: true, token: 'A'.repeat(42) }],
    ['bad alphabet', { ok: true, token: `${'A'.repeat(42)}=` }],
    ['no token', { ok: true }],
    ['not an object', 'x']
  ])('null for %s', (_label, raw) => {
    expect(parseSessionReply(raw)).toBeNull()
  })

  it('accepts base64url characters', () => {
    const token = `${'a'.repeat(40)}-_9`
    expect(parseSessionReply({ ok: true, token })).toBe(token)
  })
})
