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
  clear: () => Promise<{ ok: boolean }>
}

function bridge(): SolChatCacheBridge | undefined {
  return (window as unknown as { solus?: { solChat?: SolChatCacheBridge } }).solus?.solChat
}

const CACHE_SCHEMA_VERSION = 1
const ROLES = new Set(['user', 'assistant', 'tool'])
//: Rehydration caps (SEC review M2): a cache file must not bypass the per-turn
//: render ceiling or flood the transcript with items.
const MAX_CACHED_ITEMS = 500
const MAX_CACHED_ITEM_CHARS = 200_000 // mirrors solChatStore.MAX_TURN_CHARS

interface CachedItem {
  role: ChatItem['role']
  content: string
}

function toCachedItem(value: unknown): CachedItem | null {
  if (typeof value !== 'object' || value === null) return null
  const item = value as Record<string, unknown>
  if (typeof item.content !== 'string' || item.content.length > MAX_CACHED_ITEM_CHARS) return null
  if (typeof item.role !== 'string' || !ROLES.has(item.role)) return null
  return { role: item.role as ChatItem['role'], content: item.content }
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
    if (data.schema_version !== CACHE_SCHEMA_VERSION || !Array.isArray(data.items)) return null
    if (data.items.length > MAX_CACHED_ITEMS) return null
    const items = data.items.map(toCachedItem)
    if (items.some((item) => item === null)) return null
    // File-supplied ids never enter the live `local-` namespace (SEC review
    // H2): cache items get their own prefix so a server load always replaces
    // them wholesale and a planted item cannot pose as a live turn.
    return (items as CachedItem[]).map((item, i) => ({
      ...item,
      id: `cache-${i}`,
      citations: [],
      trace: [],
      pending: false,
      error: null,
      confirmations: []
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
    .slice(-MAX_CACHED_ITEMS)
    .map((item) => ({ role: item.role, content: item.content.slice(0, MAX_CACHED_ITEM_CHARS) }))
  void cache
    .write(
      projectId,
      conversationId,
      JSON.stringify({ schema_version: CACHE_SCHEMA_VERSION, items: settled })
    )
    .catch(() => undefined)
}

export function removeCachedChat(projectId: string, conversationId: string): void {
  void bridge()
    ?.remove(projectId, conversationId)
    .catch(() => undefined)
}

/** Purge every cached chat on this machine — the signed-in identity changed
 *  (ADR-034 amendment: transcripts belong to the previous identity). */
export function purgeAllCachedChats(): void {
  void bridge()
    ?.clear()
    .catch(() => undefined)
}
