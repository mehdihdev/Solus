// SOLUSDEV-233: the machine-local SOL chat cache under ~/.solus (ADR-034
// Layer 1 — a CACHE; the server stays the source of truth). IDs are validated
// in THIS process so a compromised renderer cannot traverse paths (§7).
import { describe, expect, it } from 'vitest'
import {
  MAX_CACHE_BYTES,
  readChatCache,
  removeChatCache,
  writeChatCache,
  type SolChatCacheDeps
} from './solChatCache'

function memoryDeps(): { deps: SolChatCacheDeps; files: Map<string, string>; dirs: string[] } {
  const files = new Map<string, string>()
  const dirs: string[] = []
  const deps: SolChatCacheDeps = {
    homedir: () => '/home/u',
    readFile: (path) => {
      const content = files.get(path)
      if (content === undefined) throw new Error('ENOENT')
      return content
    },
    writeFile: (path, content) => void files.set(path, content),
    mkdir: (path) => void dirs.push(path),
    removeFile: (path) => void files.delete(path)
  }
  return { deps, files, dirs }
}

const PID = '019f7fe5-eda7-7b38-bb8d-fe2e7fc765ae'
const CID = '019f8a11-0000-7000-8000-000000000001'

describe('solChatCache', () => {
  it('round-trips a chat under ~/.solus/projects/<pid>/sol/<cid>.json', () => {
    const { deps, files, dirs } = memoryDeps()
    expect(writeChatCache(PID, CID, '{"version":1,"items":[]}', deps)).toBe(true)
    const path = `/home/u/.solus/projects/${PID}/sol/${CID}.json`
    expect(files.has(path)).toBe(true)
    expect(dirs.some((d) => d.endsWith(`/projects/${PID}/sol`))).toBe(true)
    expect(readChatCache(PID, CID, deps)).toBe('{"version":1,"items":[]}')
    expect(removeChatCache(PID, CID, deps)).toBe(true)
    expect(readChatCache(PID, CID, deps)).toBeNull()
  })

  it('refuses unsafe ids outright — no read, no write, no remove', () => {
    const { deps, files } = memoryDeps()
    for (const evil of ['../escape', 'a/b', '..', 'x'.repeat(80), '']) {
      expect(writeChatCache(evil, CID, '{}', deps)).toBe(false)
      expect(writeChatCache(PID, evil, '{}', deps)).toBe(false)
      expect(readChatCache(evil, CID, deps)).toBeNull()
      expect(removeChatCache(PID, evil, deps)).toBe(false)
    }
    expect(files.size).toBe(0)
  })

  it('degrades to null on an oversized or unreadable cache file', () => {
    const { deps, files } = memoryDeps()
    const path = `/home/u/.solus/projects/${PID}/sol/${CID}.json`
    files.set(path, 'x'.repeat(MAX_CACHE_BYTES + 1))
    expect(readChatCache(PID, CID, deps)).toBeNull()
  })

  it('rejects oversized writes instead of filling the disk', () => {
    const { deps, files } = memoryDeps()
    expect(writeChatCache(PID, CID, 'x'.repeat(MAX_CACHE_BYTES + 1), deps)).toBe(false)
    expect(files.size).toBe(0)
  })
})
