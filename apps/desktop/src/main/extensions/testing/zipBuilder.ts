// Minimal zip WRITER for tests (SOLUSDEV-235 / EXT-05). A library writer would
// refuse to produce the hostile archives the installer must reject — symlink
// entries, traversal names, headers that lie about sizes — so entries are
// laid out by hand: local headers, a central directory, and the end record.
import { crc32, deflateRawSync } from 'node:zlib'

export interface ZipEntrySpec {
  name: string
  data?: Uint8Array | string
  /** POSIX mode stored in the high 16 bits of externalFileAttributes. */
  mode?: number
  /** Override the size the headers DECLARE (to model a lying archive). */
  declaredSize?: number
  deflate?: boolean
}

const S_IFREG = 0o100000
const S_IFDIR = 0o040000
export const S_IFLNK = 0o120000

const encoder = new TextEncoder()

function u16(n: number): Buffer {
  const b = Buffer.alloc(2)
  b.writeUInt16LE(n)
  return b
}

function u32(n: number): Buffer {
  const b = Buffer.alloc(4)
  b.writeUInt32LE(n >>> 0)
  return b
}

interface Built {
  local: Buffer
  central: Buffer
}

function buildEntry(spec: ZipEntrySpec, offset: number): Built {
  const isDir = spec.name.endsWith('/')
  const raw =
    spec.data === undefined
      ? Buffer.alloc(0)
      : Buffer.from(typeof spec.data === 'string' ? encoder.encode(spec.data) : spec.data)
  const stored = spec.deflate ? deflateRawSync(raw) : raw
  const method = spec.deflate ? 8 : 0
  const name = Buffer.from(spec.name, 'utf8')
  const crc = crc32(raw)
  const declared = spec.declaredSize ?? raw.length
  const mode = spec.mode ?? (isDir ? S_IFDIR | 0o755 : S_IFREG | 0o644)
  const common = Buffer.concat([
    u16(20), // version needed
    u16(0), // flags
    u16(method),
    u16(0), // mod time
    u16(0x21), // mod date (1980-01-01)
    u32(crc),
    u32(stored.length),
    u32(declared),
    u16(name.length),
    u16(0) // extra length
  ])
  const local = Buffer.concat([u32(0x04034b50), common, name, stored])
  const central = Buffer.concat([
    u32(0x02014b50),
    u16(0x031e), // version made by: unix (3) << 8 | 3.0
    common,
    u16(0), // comment length
    u16(0), // disk number start
    u16(0), // internal attrs
    u32((mode << 16) >>> 0), // external attrs
    u32(offset),
    name
  ])
  return { local, central }
}

/** Build a zip archive from entry specs (STORED unless `deflate`). */
export function buildZip(entries: readonly ZipEntrySpec[]): Uint8Array {
  const locals: Buffer[] = []
  const centrals: Buffer[] = []
  let offset = 0
  for (const spec of entries) {
    const built = buildEntry(spec, offset)
    locals.push(built.local)
    centrals.push(built.central)
    offset += built.local.length
  }
  const cd = Buffer.concat(centrals)
  const eocd = Buffer.concat([
    u32(0x06054b50),
    u16(0),
    u16(0),
    u16(entries.length),
    u16(entries.length),
    u32(cd.length),
    u32(offset),
    u16(0)
  ])
  return new Uint8Array(Buffer.concat([...locals, cd, eocd]))
}

/** A well-formed extension.toml for a bundle under test. */
export function manifestToml(id = 'bom', version = '1.2.0'): string {
  return [
    'schema_version = 1',
    '[extension]',
    `id = "${id}"`,
    'name = "BOM"',
    `version = "${version}"`,
    'publisher = "Solus"',
    'summary = "Bill of materials."',
    '[views]',
    'widget = { entry = "widget.html", preferred = "wide" }',
    'window = { entry = "window.html", title = "BOM", width = 960, height = 640 }',
    '[permissions]',
    'network = ["https://api.example.com"]',
    '[store]',
    'overview = "OVERVIEW.md"',
    'privacy_policy = "PRIVACY.md"',
    ''
  ].join('\n')
}

/** A complete, valid bundle: manifest + the files it references. */
export function validBundle(id = 'bom', version = '1.2.0'): Uint8Array {
  return buildZip([
    { name: 'extension.toml', data: manifestToml(id, version) },
    { name: 'widget.html', data: '<!doctype html><p>widget</p>' },
    { name: 'window.html', data: '<!doctype html><p>window</p>' },
    { name: 'assets/', data: undefined },
    { name: 'assets/app.js', data: 'console.log(1)', deflate: true },
    { name: 'OVERVIEW.md', data: '# BOM' },
    { name: 'PRIVACY.md', data: 'none' }
  ])
}
