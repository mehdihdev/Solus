// Test double for the ExtensionFs surface (SOLUSDEV-235 / EXT-05): an
// in-memory tree of files + directories with recorded modes, so every install /
// index / protocol decision is provable without touching the real home dir.
// Directory rename/remove move or drop every path under the prefix, which is
// what the temp-dir-then-rename install relies on.
import type { ExtensionFs } from '../extensionFs'

export interface FakeExtensionFs extends ExtensionFs {
  files: Map<string, Uint8Array>
  dirs: Set<string>
  modes: Map<string, number>
  /** Symlink table consulted by `realpath`: path → target. */
  links: Map<string, string>
  text: (path: string) => string | undefined
}

const encoder = new TextEncoder()
const decoder = new TextDecoder()

function under(prefix: string, path: string): boolean {
  return path === prefix || path.startsWith(`${prefix}/`)
}

export function fakeExtensionFs(overrides: Partial<ExtensionFs> = {}): FakeExtensionFs {
  const files = new Map<string, Uint8Array>()
  const dirs = new Set<string>()
  const modes = new Map<string, number>()
  const links = new Map<string, string>()
  let suffix = 0
  const resolveLinks = (path: string): string => {
    for (const [from, to] of links) if (under(from, path)) return to + path.slice(from.length)
    return path
  }
  const fs: FakeExtensionFs = {
    files,
    dirs,
    modes,
    links,
    text: (path) => {
      const bytes = files.get(path)
      return bytes === undefined ? undefined : decoder.decode(bytes)
    },
    homedir: () => '/home/tester',
    readFile: (path) => {
      const bytes = files.get(resolveLinks(path))
      if (bytes === undefined) throw new Error(`ENOENT: ${path}`)
      return bytes
    },
    writeFile: (path, data, mode) => {
      files.set(path, typeof data === 'string' ? encoder.encode(data) : data)
      modes.set(path, mode)
    },
    rename: (from, to) => {
      const movedFiles = [...files.keys()].filter((p) => under(from, p))
      const movedDirs = [...dirs].filter((p) => under(from, p))
      if (movedFiles.length === 0 && movedDirs.length === 0) throw new Error(`ENOENT: ${from}`)
      for (const p of movedFiles) {
        const bytes = files.get(p) as Uint8Array
        const mode = modes.get(p)
        files.delete(p)
        files.set(to + p.slice(from.length), bytes)
        if (mode !== undefined) modes.set(to + p.slice(from.length), mode)
      }
      for (const p of movedDirs) {
        const mode = modes.get(p)
        dirs.delete(p)
        dirs.add(to + p.slice(from.length))
        if (mode !== undefined) modes.set(to + p.slice(from.length), mode)
      }
    },
    mkdir: (path, mode) => {
      dirs.add(path)
      modes.set(path, mode)
    },
    chmod: (path, mode) => {
      modes.set(path, mode)
    },
    remove: (path) => {
      for (const p of [...files.keys()]) if (under(path, p)) files.delete(p)
      for (const p of [...dirs]) if (under(path, p)) dirs.delete(p)
    },
    realpath: (path) => {
      const real = resolveLinks(path)
      return files.has(real) || dirs.has(real) ? real : null
    },
    isDirectory: (path) => dirs.has(resolveLinks(path)),
    fileSize: (path) => {
      if (links.has(path)) return null // a symlink at the path itself is refused
      const bytes = files.get(path)
      return bytes === undefined ? null : bytes.byteLength
    },
    tempSuffix: () => `tmp${suffix++}`,
    now: () => new Date('2026-09-03T12:00:00Z'),
    warn: () => undefined,
    ...overrides
  }
  return fs
}

/** Register a directory (and its ancestors) in the fake tree. */
export function seedDir(fs: FakeExtensionFs, path: string): void {
  const parts = path.split('/').filter(Boolean)
  for (let i = 1; i <= parts.length; i++) fs.dirs.add(`/${parts.slice(0, i).join('/')}`)
}

/** Register a text file (and its parent directories). */
export function seedFile(fs: FakeExtensionFs, path: string, content: string): void {
  seedDir(fs, path.slice(0, path.lastIndexOf('/')))
  fs.files.set(path, encoder.encode(content))
}
