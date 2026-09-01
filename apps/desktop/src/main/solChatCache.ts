// SOLUSDEV-233: machine-local SOL chat cache — ~/.solus/projects/<pid>/sol/
// (ADR-034 Layer 1: caches). The server remains the source of truth for
// conversations; this only makes returning to a chat instant and past chats
// readable offline. Content is an opaque JSON string the renderer owns; THIS
// process validates ids (uuid-shaped, no separators) so a compromised renderer
// cannot traverse paths, and bounds sizes both ways (§7). Deps-injected like
// localState so tests need no real filesystem.
import { isSafeProjectId, SOLUS_HOME_DIRNAME, SOLUS_HOME_MODE } from '@solus/shared-types'
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

export interface SolChatCacheDeps {
  homedir: () => string
  readFile: (path: string) => string
  writeFile: (path: string, content: string, mode: number) => void
  mkdir: (path: string, mode: number) => void
  removeFile: (path: string) => void
}

/** Cache files hold the user's own chat text — owner read/write only. */
const CACHE_FILE_MODE = 0o600

/** A transcript cache past this is corruption or abuse — degrade, don't chew. */
export const MAX_CACHE_BYTES = 2 * 1024 * 1024

function cachePath(
  projectId: string,
  conversationId: string,
  deps: SolChatCacheDeps
): string | null {
  // Conversation ids are uuid-shaped exactly like project ids — one validator,
  // enforced main-process-side (§7 path traversal), plus a length cap the
  // shared charset check doesn't carry (uuids are 36 chars; 64 is headroom).
  const safe = (id: string): boolean => isSafeProjectId(id) && id.length <= 64
  if (!safe(projectId) || !safe(conversationId)) return null
  return join(
    deps.homedir(),
    SOLUS_HOME_DIRNAME,
    'projects',
    projectId,
    'sol',
    `${conversationId}.json`
  )
}

export function readChatCache(
  projectId: string,
  conversationId: string,
  deps: SolChatCacheDeps
): string | null {
  const path = cachePath(projectId, conversationId, deps)
  if (path === null) return null
  try {
    const content = deps.readFile(path)
    return content.length <= MAX_CACHE_BYTES ? content : null
  } catch {
    return null
  }
}

export function writeChatCache(
  projectId: string,
  conversationId: string,
  content: string,
  deps: SolChatCacheDeps
): boolean {
  const path = cachePath(projectId, conversationId, deps)
  if (path === null || typeof content !== 'string' || content.length > MAX_CACHE_BYTES) {
    return false
  }
  try {
    const dir = join(deps.homedir(), SOLUS_HOME_DIRNAME, 'projects', projectId, 'sol')
    deps.mkdir(dir, SOLUS_HOME_MODE)
    deps.writeFile(path, content, CACHE_FILE_MODE)
    return true
  } catch {
    return false
  }
}

export function removeChatCache(
  projectId: string,
  conversationId: string,
  deps: SolChatCacheDeps
): boolean {
  const path = cachePath(projectId, conversationId, deps)
  if (path === null) return false
  try {
    deps.removeFile(path)
    return true
  } catch {
    return false
  }
}

export const realSolChatCacheDeps: SolChatCacheDeps = {
  homedir,
  readFile: (path) => readFileSync(path, 'utf8'),
  writeFile: (path, content, mode) => writeFileSync(path, content, { encoding: 'utf8', mode }),
  mkdir: (path, mode) => void mkdirSync(path, { recursive: true, mode }),
  removeFile: (path) => rmSync(path, { force: true })
}
