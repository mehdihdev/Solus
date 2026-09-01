// SOLUSDEV-233: the machine-local SOL chat cache under ~/.solus (ADR-034 as
// amended 2026-09-01). IDs are validated in THIS process (§7 path traversal),
// sizes are gated in BYTES before anything is materialized, writes are atomic
// temp+rename, and a newer schema_version's file is read-only to this app.
import { describe, expect, it } from 'vitest'
import {
  MAX_CACHE_BYTES,
  clearAllChatCaches,
  readChatCache,
  removeChatCache,
  solChatCacheIpc,
  writeChatCache,
  type SolChatCacheDeps
} from './solChatCache'

interface Memory {
  deps: SolChatCacheDeps
  files: Map<string, string>
  dirs: Set<string>
  renames: Array<{ from: string; to: string }>
  removedDirs: string[]
}

function memoryDeps(): Memory {
  const files = new Map<string, string>()
  const dirs = new Set<string>()
  const renames: Array<{ from: string; to: string }> = []
  const removedDirs: string[] = []
  const deps: SolChatCacheDeps = {
    homedir: () => '/home/u',
    readFile: (path) => {
      const content = files.get(path)
      if (content === undefined) throw new Error('ENOENT')
      return content
    },
    writeFile: (path, content) => void files.set(path, content),
    replaceFile: (from, to) => {
      const content = files.get(from)
      if (content === undefined) throw new Error('ENOENT')
      files.delete(from)
      files.set(to, content)
      renames.push({ from, to })
    },
    mkdir: (path) => void dirs.add(path),
    chmod: () => undefined,
    removeFile: (path) => void files.delete(path),
    removeDir: (path) => {
      removedDirs.push(path)
      for (const key of [...files.keys()]) if (key.startsWith(path)) files.delete(key)
    },
    fileSize: (path) => {
      const content = files.get(path)
      return content === undefined ? null : Buffer.byteLength(content, 'utf8')
    },
    listDirs: (path) => {
      const names = new Set<string>()
      for (const key of files.keys()) {
        if (key.startsWith(`${path}/`)) names.add(key.slice(path.length + 1).split('/')[0])
      }
      return [...names]
    }
  }
  return { deps, files, dirs, renames, removedDirs }
}

const PID = '019f7fe5-eda7-7b38-bb8d-fe2e7fc765ae'
const CID = '019f8a11-0000-7000-8000-000000000001'
const PATH = `/home/u/.solus/projects/${PID}/sol/${CID}.json`
const V1 = '{"schema_version":1,"items":[]}'

describe('solChatCache', () => {
  it('round-trips a chat atomically (temp + rename, never in place)', () => {
    const m = memoryDeps()
    expect(writeChatCache(PID, CID, V1, m.deps)).toBe(true)
    expect(m.files.get(PATH)).toBe(V1)
    expect(m.renames).toHaveLength(1)
    expect(m.renames[0].to).toBe(PATH)
    expect(m.renames[0].from).not.toBe(PATH) // written beside, renamed over
    expect(readChatCache(PID, CID, m.deps)).toBe(V1)
    expect(removeChatCache(PID, CID, m.deps)).toBe(true)
    expect(readChatCache(PID, CID, m.deps)).toBeNull()
  })

  it('refuses unsafe ids outright — no read, no write, no remove', () => {
    const m = memoryDeps()
    for (const evil of ['../escape', 'a/b', '..', 'x'.repeat(80), '']) {
      expect(writeChatCache(evil, CID, V1, m.deps)).toBe(false)
      expect(writeChatCache(PID, evil, V1, m.deps)).toBe(false)
      expect(readChatCache(evil, CID, m.deps)).toBeNull()
      expect(removeChatCache(PID, evil, m.deps)).toBe(false)
    }
    expect(m.files.size).toBe(0)
  })

  it('gates reads on BYTE size and file kind before materializing', () => {
    const m = memoryDeps()
    // Oversized (multi-byte content past the byte cap even at fewer chars).
    m.files.set(PATH, '指'.repeat(Math.ceil(MAX_CACHE_BYTES / 3) + 10))
    expect(readChatCache(PID, CID, m.deps)).toBeNull()
    // Not a regular file (fileSize null models a symlink/dir).
    m.files.delete(PATH)
    const deps = { ...m.deps, fileSize: () => null }
    m.files.set(PATH, V1)
    expect(readChatCache(PID, CID, deps)).toBeNull()
  })

  it('rejects oversized writes (bytes, not UTF-16 units) and versionless payloads', () => {
    const m = memoryDeps()
    expect(writeChatCache(PID, CID, '指'.repeat(MAX_CACHE_BYTES / 3 + 10), m.deps)).toBe(false)
    expect(writeChatCache(PID, CID, '{"items":[]}', m.deps)).toBe(false) // no schema_version
    expect(m.files.size).toBe(0)
  })

  it('never clobbers a NEWER schema_version file (ADR-034 rule 6)', () => {
    const m = memoryDeps()
    m.files.set(PATH, '{"schema_version":2,"items":[]}')
    expect(writeChatCache(PID, CID, V1, m.deps)).toBe(false)
    expect(m.files.get(PATH)).toBe('{"schema_version":2,"items":[]}')
  })

  it('clearAllChatCaches purges every project sol dir and nothing else', () => {
    const m = memoryDeps()
    writeChatCache(PID, CID, V1, m.deps)
    m.files.set('/home/u/.solus/projects.json', '{}')
    expect(clearAllChatCaches(m.deps)).toBe(true)
    expect(m.removedDirs).toEqual([`/home/u/.solus/projects/${PID}/sol`])
    expect(m.files.has(PATH)).toBe(false)
    expect(m.files.has('/home/u/.solus/projects.json')).toBe(true)
  })
})

describe('solChatCacheIpc (SEC M4 — the gate itself is tested)', () => {
  it('refuses a foreign sender on every channel', () => {
    const m = memoryDeps()
    writeChatCache(PID, CID, V1, m.deps)
    expect(solChatCacheIpc.read(false, PID, CID, m.deps)).toBeNull()
    expect(solChatCacheIpc.write(false, PID, CID, V1, m.deps)).toEqual({ ok: false })
    expect(solChatCacheIpc.remove(false, PID, CID, m.deps)).toEqual({ ok: false })
    expect(solChatCacheIpc.clear(false, m.deps)).toEqual({ ok: false })
    expect(m.files.get(PATH)).toBe(V1) // nothing was touched
  })

  it('refuses non-string args and oversize content at the boundary', () => {
    const m = memoryDeps()
    expect(solChatCacheIpc.read(true, 7, CID, m.deps)).toBeNull()
    expect(solChatCacheIpc.write(true, PID, CID, 42, m.deps)).toEqual({ ok: false })
    expect(solChatCacheIpc.write(true, PID, CID, 'x'.repeat(MAX_CACHE_BYTES + 1), m.deps)).toEqual({
      ok: false
    })
    expect(solChatCacheIpc.remove(true, PID, null, m.deps)).toEqual({ ok: false })
  })

  it('passes valid requests through', () => {
    const m = memoryDeps()
    expect(solChatCacheIpc.write(true, PID, CID, V1, m.deps)).toEqual({ ok: true })
    expect(solChatCacheIpc.read(true, PID, CID, m.deps)).toBe(V1)
    expect(solChatCacheIpc.clear(true, m.deps)).toEqual({ ok: true })
    expect(solChatCacheIpc.read(true, PID, CID, m.deps)).toBeNull()
  })
})
