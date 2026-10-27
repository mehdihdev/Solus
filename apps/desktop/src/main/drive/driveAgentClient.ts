// SOLUSDEV-319 drive slice 3b (docs/architecture/sol-drive.md §2.1, §5 "Main
// and the agent"): main's client for the solus-input agent's unix socket.
// Electron main is the peer the agent checks (com.solusforge.solus). Wire
// protocol v1: one request per connection — one `\n`-terminated JSON line —
// one JSON line back, then the agent closes. One deadline covers connect,
// write and read; the reply is capped; anything odd answers null. The session
// token is never logged (no reply content is logged at all).
import { createConnection, type Socket } from 'node:net'
import { parseTrustOutput, type DriveTrustResult } from './driveHelper'

export const AGENT_DEADLINE_MS = 5_000
export const AGENT_MAX_REPLY_BYTES = 64 * 1024
/** 32 random bytes, base64url without padding. */
const SESSION_TOKEN = /^[A-Za-z0-9_-]{43}$/

export interface AgentRequestOptions {
  deadlineMs?: number
  /** Injected for tests; defaults to `net.createConnection(path)`. */
  connect?: (path: string) => Socket
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

function parseOneLine(raw: string): unknown {
  const lines = raw.split('\n').filter((line) => line.trim().length > 0)
  if (lines.length !== 1) return null
  try {
    return JSON.parse(lines[0])
  } catch {
    return null
  }
}

/** One request, one reply object (or null on any failure). */
export function agentRequest(
  socketPath: string,
  request: Record<string, unknown>,
  options: AgentRequestOptions = {}
): Promise<Record<string, unknown> | null> {
  const connect = options.connect ?? ((path: string) => createConnection(path))
  return new Promise((resolve) => {
    let settled = false
    const chunks: Buffer[] = []
    let size = 0
    let conn: Socket | null = null
    const finish = (value: Record<string, unknown> | null): void => {
      if (settled) return
      settled = true
      clearTimeout(deadline)
      conn?.destroy()
      resolve(value)
    }
    const deadline = setTimeout(() => finish(null), options.deadlineMs ?? AGENT_DEADLINE_MS)
    try {
      conn = connect(socketPath)
    } catch {
      return finish(null)
    }
    conn.on('error', () => finish(null))
    conn.on('data', (chunk: Buffer) => {
      size += chunk.length
      if (size > AGENT_MAX_REPLY_BYTES) return finish(null)
      chunks.push(chunk)
    })
    conn.on('end', () => {
      const value = parseOneLine(Buffer.concat(chunks).toString('utf8'))
      finish(isRecord(value) ? value : null)
    })
    conn.on('close', () => finish(null)) // closed without a full reply
    conn.write(`${JSON.stringify(request)}\n`)
  })
}

/** `{ok:true, token}` with a well-formed token, else null. */
export function parseSessionReply(reply: unknown): string | null {
  if (!isRecord(reply) || reply.ok !== true) return null
  return typeof reply.token === 'string' && SESSION_TOKEN.test(reply.token) ? reply.token : null
}

/** A fresh session token (replaces any previous one in the agent). */
export async function requestAgentSession(
  socketPath: string,
  options?: AgentRequestOptions
): Promise<string | null> {
  return parseSessionReply(await agentRequest(socketPath, { v: 1, op: 'session' }, options))
}

/** The helper's grants; `prompt` asks macOS to show both permission prompts. */
export async function requestAgentTrust(
  socketPath: string,
  prompt: boolean,
  options?: AgentRequestOptions
): Promise<DriveTrustResult | null> {
  const reply = await agentRequest(socketPath, { v: 1, op: 'trust', prompt }, options)
  return reply === null ? null : parseTrustOutput(JSON.stringify(reply))
}
