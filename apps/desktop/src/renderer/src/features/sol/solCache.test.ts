// SOLUSDEV-233: renderer side of the ~/.solus chat cache — defensive parsing,
// settled-turns-only writes, graceful no-bridge degradation.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readCachedChat, removeCachedChat, writeCachedChat } from './solCache'
import type { ChatItem } from './solChatStore'

const read = vi.fn()
const write = vi.fn().mockResolvedValue({ ok: true })
const remove = vi.fn().mockResolvedValue({ ok: true })

function installBridge(): void {
  ;(window as unknown as { solus?: unknown }).solus = { solChat: { read, write, remove } }
}

function item(overrides: Partial<ChatItem>): ChatItem {
  return {
    id: 'x',
    role: 'user',
    content: 'hi',
    citations: [],
    trace: [],
    pending: false,
    error: null,
    confirmations: [],
    ...overrides
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  installBridge()
})
afterEach(() => {
  delete (window as unknown as { solus?: unknown }).solus
})

describe('solCache', () => {
  it('round-trips settled turns and rehydrates them as non-pending items', async () => {
    writeCachedChat('p1', 'c1', [
      item({ id: 't1', role: 'user', content: 'q' }),
      item({ id: 't2', role: 'assistant', content: 'a' }),
      item({ id: 't3', pending: true, content: 'streaming…' }), // never cached
      item({ id: 't4', error: 'failed', content: '' }) // never cached
    ])
    const written = write.mock.calls[0]
    expect(written[0]).toBe('p1')
    expect(JSON.parse(written[2]).schema_version).toBe(1) // ADR-034 contract field
    read.mockResolvedValue(written[2])
    const items = await readCachedChat('p1', 'c1')
    expect(items?.map((m) => m.content)).toEqual(['q', 'a'])
    // File-supplied ids never enter the live `local-` namespace (SEC H2).
    expect(items?.every((m) => m.id.startsWith('cache-'))).toBe(true)
    expect(items?.every((m) => !m.pending && m.confirmations.length === 0)).toBe(true)
  })

  it('discards malformed cache files instead of rendering them', async () => {
    const oversizedItem = JSON.stringify({
      schema_version: 1,
      items: [{ role: 'assistant', content: 'x'.repeat(200_001) }]
    })
    const floodedItems = JSON.stringify({
      schema_version: 1,
      items: Array.from({ length: 501 }, () => ({ role: 'user', content: 'x' }))
    })
    for (const raw of [
      'not json',
      '{"schema_version":9,"items":[]}', // newer schema is read-only, never rendered
      '{"schema_version":1,"items":[{"role":1}]}',
      oversizedItem, // per-item render ceiling (SEC M2)
      floodedItems // item-count cap (SEC M2)
    ]) {
      read.mockResolvedValue(raw)
      expect(await readCachedChat('p1', 'c1')).toBeNull()
    }
  })

  it('degrades to null / no-op when the bridge is absent (web, tests)', async () => {
    delete (window as unknown as { solus?: unknown }).solus
    expect(await readCachedChat('p1', 'c1')).toBeNull()
    writeCachedChat('p1', 'c1', [])
    removeCachedChat('p1', 'c1')
    expect(write).not.toHaveBeenCalled()
    expect(remove).not.toHaveBeenCalled()
  })

  it('removes a cached chat', () => {
    removeCachedChat('p1', 'c1')
    expect(remove).toHaveBeenCalledWith('p1', 'c1')
  })
})
