// SOLUSDEV-233: renderer side of the machine-local SOL chat cache
// (~/.solus/projects/<pid>/sol/, ADR-034 Layer 1). The SERVER stays the source
// of truth — this only paints a returning chat instantly and keeps past chats
// readable offline. Parsed defensively: a cache file is machine-local data,
// but it is still parsed input — malformed shapes are discarded, and only the
// serializable, settled fields of a turn are stored (never confirmations,
// never pending state).
import type { ChatItem } from './solChatStore'

interface SolChatCacheBridge {
  read: (projectId: string, conversationId: string) => Promise<string | null>
  write: (projectId: string, conversationId: string, content: string) => Promise<{ ok: boolean }>
  remove: (projectId: string, conversationId: string) => Promise<{ ok: boolean }>
}

function bridge(): SolChatCacheBridge | undefined {
  return (window as unknown as { solus?: { solChat?: SolChatCacheBridge } }).solus?.solChat
}

const CACHE_VERSION = 1
const ROLES = new Set(['user', 'assistant', 'tool'])

interface CachedItem {
  id: string
  role: ChatItem['role']
  content: string
}

function toCachedItem(value: unknown): CachedItem | null {
  if (typeof value !== 'object' || value === null) return null
  const item = value as Record<string, unknown>
  if (typeof item.id !== 'string' || typeof item.content !== 'string') return null
  if (typeof item.role !== 'string' || !ROLES.has(item.role)) return null
  return { id: item.id, role: item.role as ChatItem['role'], content: item.content }
}

/** Cached turns for a chat, or null (no bridge / no file / malformed). */
export async function readCachedChat(
  projectId: string,
  conversationId: string
): Promise<ChatItem[] | null> {
  const cache = bridge()
  if (!cache) return null
  try {
    const raw = await cache.read(projectId, conversationId)
    if (raw === null) return null
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return null
    const data = parsed as Record<string, unknown>
    if (data.version !== CACHE_VERSION || !Array.isArray(data.items)) return null
    const items = data.items.map(toCachedItem)
    if (items.some((item) => item === null)) return null
    return (items as CachedItem[]).map((item) => ({
      ...item,
      citations: [],
      trace: [],
      pending: false,
      error: null,
      confirmation: null
    }))
  } catch {
    return null
  }
}

/** Persist the settled turns of a chat (fire-and-forget; failures are silent —
 *  the cache is a convenience, never load-bearing). */
export function writeCachedChat(
  projectId: string,
  conversationId: string,
  items: readonly ChatItem[]
): void {
  const cache = bridge()
  if (!cache) return
  const settled = items
    .filter((item) => !item.pending && item.error === null)
    .map((item) => ({ id: item.id, role: item.role, content: item.content }))
  void cache
    .write(projectId, conversationId, JSON.stringify({ version: CACHE_VERSION, items: settled }))
    .catch(() => undefined)
}

export function removeCachedChat(projectId: string, conversationId: string): void {
  void bridge()
    ?.remove(projectId, conversationId)
    .catch(() => undefined)
}
