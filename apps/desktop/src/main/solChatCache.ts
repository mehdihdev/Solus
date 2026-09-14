// SOLUSDEV-233: machine-local SOL chat cache — ~/.solus/projects/<pid>/sol/
// (ADR-034 as amended 2026-09-01: schema_version 1, atomic temp+rename writes,
// 0600 files under the 0700 home, 2 MB byte cap, newer schema_version files
// are read-only). The server remains the source of truth for conversations;
// this only makes returning to a chat instant and past chats readable offline.
// Content is an opaque JSON string the renderer owns; THIS process validates
// ids (uuid-shaped, capped length) so a compromised renderer cannot traverse
// paths, gates sizes in BYTES before materializing anything, and refuses
// symlinks (§7). Deps-injected like localState so tests need no filesystem.
import { isSafeProjectId, SOLUS_HOME_DIRNAME, SOLUS_HOME_MODE } from '@solus/shared-types'
import { randomBytes } from 'node:crypto'
import {
  chmodSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync
} from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

export interface SolChatCacheDeps {
  homedir: () => string
  readFile: (path: string) => string
  writeFile: (path: string, content: string, mode: number) => void
  /** Move `from` over `to`, replacing it — atomic on POSIX. */
  replaceFile: (from: string, to: string) => void
  mkdir: (path: string, mode: number) => void
  chmod: (path: string, mode: number) => void
  removeFile: (path: string) => void
  removeDir: (path: string) => void
  /** Size in bytes when `path` is a REGULAR file (lstat — a symlink planted at
   *  the cache path is refused, never followed); null otherwise. */
  fileSize: (path: string) => number | null
  /** Subdirectory names of `path` ([] when missing). */
  listDirs: (path: string) => string[]
}

/** Cache files hold the user's own chat text — owner read/write only. */
const CACHE_FILE_MODE = 0o600

/** BYTE cap, both directions — a transcript cache past this is corruption or
 *  abuse; degrade, don't chew (measured with Buffer.byteLength, not UTF-16). */
export const MAX_CACHE_BYTES = 2 * 1024 * 1024

const utf8Bytes = (content: string): number => Buffer.byteLength(content, 'utf8')

function solDir(projectId: string, deps: SolChatCacheDeps): string {
  return join(deps.homedir(), SOLUS_HOME_DIRNAME, 'projects', projectId, 'sol')
}

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
  return join(solDir(projectId, deps), `${conversationId}.json`)
}

export function readChatCache(
  projectId: string,
  conversationId: string,
  deps: SolChatCacheDeps
): string | null {
  const path = cachePath(projectId, conversationId, deps)
  if (path === null) return null
  try {
    // Size- and kind-gate BEFORE materializing: an oversized or symlinked
    // file is refused without ever being read (§7).
    const size = deps.fileSize(path)
    if (size === null || size > MAX_CACHE_BYTES) return null
    return deps.readFile(path)
  } catch {
    return null
  }
}

/** The file's schema_version, or null when unreadable. Cheap minimal parse so
 *  a NEWER schema's file is never clobbered by an older app (ADR-034 rule 6). */
function existingSchemaVersion(path: string, deps: SolChatCacheDeps): number | null {
  try {
    const size = deps.fileSize(path)
    if (size === null || size > MAX_CACHE_BYTES) return null
    const parsed: unknown = JSON.parse(deps.readFile(path))
    const version = (parsed as { schema_version?: unknown })?.schema_version
    return typeof version === 'number' ? version : null
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
  if (path === null || typeof content !== 'string' || utf8Bytes(content) > MAX_CACHE_BYTES) {
    return false
  }
  try {
    const incoming: unknown = JSON.parse(content)
    const incomingVersion = (incoming as { schema_version?: unknown })?.schema_version
    if (typeof incomingVersion !== 'number') return false
    // A file written by a NEWER app version is read-only to this one.
    const existing = existingSchemaVersion(path, deps)
    if (existing !== null && existing > incomingVersion) return false

    const dir = solDir(projectId, deps)
    deps.mkdir(dir, SOLUS_HOME_MODE)
    // Re-tighten the home even when it pre-existed under a looser umask.
    deps.chmod(join(deps.homedir(), SOLUS_HOME_DIRNAME), SOLUS_HOME_MODE)
    // Atomic: temp in the SAME directory, then rename over the target — a
    // crash never tears the file, and a symlink at the target is REPLACED,
    // never written through (ADR-034 write rule).
    const temp = join(dir, `.${conversationId}.${randomBytes(4).toString('hex')}.tmp`)
    deps.writeFile(temp, content, CACHE_FILE_MODE)
    deps.replaceFile(temp, path)
    deps.chmod(path, CACHE_FILE_MODE)
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

/** Purge every project's chat cache — account identity changed (ADR-034
 *  amendment: cached transcripts belong to the previous identity). */
export function clearAllChatCaches(deps: SolChatCacheDeps): boolean {
  try {
    const projectsDir = join(deps.homedir(), SOLUS_HOME_DIRNAME, 'projects')
    for (const dir of deps.listDirs(projectsDir)) {
      deps.removeDir(join(projectsDir, dir, 'sol'))
    }
    return true
  } catch {
    return false
  }
}

/** The IPC seam (SEC review M4): every channel's full decision — sender gate,
 *  argument shapes, size caps — lives HERE where it is testable; index.ts only
 *  wires ipcMain to these with the real sender check and deps. */
export const solChatCacheIpc = {
  read(
    senderOk: boolean,
    projectId: unknown,
    conversationId: unknown,
    deps: SolChatCacheDeps
  ): ReturnType<typeof readChatCache> {
    return senderOk && typeof projectId === 'string' && typeof conversationId === 'string'
      ? readChatCache(projectId, conversationId, deps)
      : null
  },
  write(
    senderOk: boolean,
    projectId: unknown,
    conversationId: unknown,
    content: unknown,
    deps: SolChatCacheDeps
  ): { ok: boolean } {
    const valid =
      senderOk &&
      typeof projectId === 'string' &&
      typeof conversationId === 'string' &&
      typeof content === 'string' &&
      utf8Bytes(content) <= MAX_CACHE_BYTES
    return { ok: valid ? writeChatCache(projectId, conversationId, content, deps) : false }
  },
  remove(
    senderOk: boolean,
    projectId: unknown,
    conversationId: unknown,
    deps: SolChatCacheDeps
  ): { ok: boolean } {
    return {
      ok:
        senderOk && typeof projectId === 'string' && typeof conversationId === 'string'
          ? removeChatCache(projectId, conversationId, deps)
          : false
    }
  },
  clear(senderOk: boolean, deps: SolChatCacheDeps): { ok: boolean } {
    return { ok: senderOk ? clearAllChatCaches(deps) : false }
  }
}

export const realSolChatCacheDeps: SolChatCacheDeps = {
  homedir,
  readFile: (path) => readFileSync(path, 'utf8'),
  writeFile: (path, content, mode) => writeFileSync(path, content, { encoding: 'utf8', mode }),
  replaceFile: (from, to) => renameSync(from, to),
  mkdir: (path, mode) => void mkdirSync(path, { recursive: true, mode }),
  chmod: (path, mode) => chmodSync(path, mode),
  removeFile: (path) => rmSync(path, { force: true }),
  removeDir: (path) => rmSync(path, { recursive: true, force: true }),
  fileSize: (path) => {
    try {
      const stat = lstatSync(path)
      return stat.isFile() ? stat.size : null
    } catch {
      return null
    }
  },
  listDirs: (path) => {
    try {
      return readdirSync(path, { withFileTypes: true })
        .filter((entry) => entry.isDirectory())
        .map((entry) => entry.name)
    } catch {
      return []
    }
  }
}
