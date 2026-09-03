// SOLUSDEV-235 / EXT-05 — ~/.solus/extensions/index.json (ADR-034 amendment
// 2026-09-03): which extension versions are installed on THIS machine and the
// content hash each was verified against. The registry server stays the source
// of truth; this file is a cache record and may be deleted at any time.
//
// Ground rules inherited from localState.ts: JSON with schema_version, atomic
// temp+rename, 0600 under 0700 dirs, ≤ 1 MiB, corrupt → empty (and
// overwritable), NEWER schema_version → read-only. The file is fork-readable
// and hand-editable, so every value is validated on the way in AND out.
import { isSafeExtensionId, SOLUS_HOME_DIRNAME, SOLUS_HOME_MODE } from '@solus/shared-types'
import { isAbsolute, join } from 'node:path'
import { EXTENSION_DIR_MODE, EXTENSION_FILE_MODE, type ExtensionFs } from './extensionFs'
import { EXTENSIONS_INDEX_FILENAME, extensionsRoot, isSafeExtensionVersion } from './extensionPaths'

export const EXTENSION_INDEX_SCHEMA_VERSION = 1
export const MAX_INDEX_BYTES = 1024 * 1024

const SHA256_HEX_RE = /^[0-9a-f]{64}$/
const MAX_TIMESTAMP_LENGTH = 64
const ENTRY_FIELDS = ['version', 'contentHash', 'installedAt', 'source', 'devPath']
const SOURCES = ['registry', 'dev'] as const

export type InstallSource = (typeof SOURCES)[number]

export interface InstalledExtension {
  readonly version: string
  /** sha256 hex of the bundle zip (registry) or of extension.toml (dev). */
  readonly contentHash: string
  readonly installedAt: string
  readonly source: InstallSource
  /** Absolute unpacked folder — dev entries only; served in place. */
  readonly devPath?: string
}

export interface ExtensionIndex {
  readonly schema_version: typeof EXTENSION_INDEX_SCHEMA_VERSION
  readonly installed: Readonly<Record<string, InstalledExtension>>
}

export type IndexParseResult =
  | { readonly ok: true; readonly index: ExtensionIndex }
  | { readonly ok: false; readonly reason: 'invalid' | 'newer' }

export function emptyExtensionIndex(): ExtensionIndex {
  return { schema_version: EXTENSION_INDEX_SCHEMA_VERSION, installed: Object.create(null) }
}

export function isSha256Hex(value: unknown): value is string {
  return typeof value === 'string' && SHA256_HEX_RE.test(value)
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

function hasValidDevPath(v: Record<string, unknown>): boolean {
  if (v.source === 'dev') return typeof v.devPath === 'string' && isAbsolute(v.devPath)
  return v.devPath === undefined
}

function isInstallSource(v: unknown): v is InstallSource {
  return typeof v === 'string' && (SOURCES as readonly string[]).includes(v)
}

function hasEntryShape(v: Record<string, unknown>): boolean {
  const { version, contentHash, installedAt } = v
  return (
    Object.keys(v).every((k) => ENTRY_FIELDS.includes(k)) &&
    typeof version === 'string' &&
    isSafeExtensionVersion(version) &&
    isSha256Hex(contentHash) &&
    typeof installedAt === 'string' &&
    installedAt.length <= MAX_TIMESTAMP_LENGTH
  )
}

function parseEntry(v: unknown): InstalledExtension | null {
  if (!isPlainObject(v) || !hasEntryShape(v) || !isInstallSource(v.source)) return null
  if (!hasValidDevPath(v)) return null
  return {
    version: v.version as string,
    contentHash: v.contentHash as string,
    installedAt: v.installedAt as string,
    source: v.source,
    ...(typeof v.devPath === 'string' ? { devPath: v.devPath } : {})
  }
}

function parseInstalled(raw: unknown): Record<string, InstalledExtension> | null {
  if (!isPlainObject(raw)) return null
  const installed: Record<string, InstalledExtension> = Object.create(null)
  for (const [id, value] of Object.entries(raw)) {
    const entry = isSafeExtensionId(id) ? parseEntry(value) : null
    if (entry === null) return null
    installed[id] = entry
  }
  return installed
}

/** Strict parse: unknown fields, unsafe ids, and malformed entries all reject. */
export function parseExtensionIndex(value: unknown): IndexParseResult {
  if (!isPlainObject(value)) return { ok: false, reason: 'invalid' }
  const sv = value.schema_version
  if (typeof sv !== 'number' || !Number.isInteger(sv)) return { ok: false, reason: 'invalid' }
  if (sv > EXTENSION_INDEX_SCHEMA_VERSION) return { ok: false, reason: 'newer' }
  const known = ['schema_version', 'installed']
  if (sv !== EXTENSION_INDEX_SCHEMA_VERSION || Object.keys(value).some((k) => !known.includes(k)))
    return { ok: false, reason: 'invalid' }
  const installed = parseInstalled(value.installed)
  if (installed === null) return { ok: false, reason: 'invalid' }
  return { ok: true, index: { schema_version: EXTENSION_INDEX_SCHEMA_VERSION, installed } }
}

export interface IndexRead {
  index: ExtensionIndex
  /** False when a NEWER schema wrote the file — we must not rewrite it. */
  writable: boolean
}

function indexPath(fs: ExtensionFs): string {
  return join(extensionsRoot(fs.homedir()), EXTENSIONS_INDEX_FILENAME)
}

function degraded(fs: ExtensionFs, why: string): IndexRead {
  fs.warn(`[extensions] index.json ${why}; treating as empty`)
  return { index: emptyExtensionIndex(), writable: true }
}

/** Read the index, degrading — never throwing: missing/corrupt ⇒ empty and
 *  writable; newer ⇒ empty and READ-ONLY. */
export function readExtensionIndex(fs: ExtensionFs): IndexRead {
  let bytes: Uint8Array
  try {
    bytes = fs.readFile(indexPath(fs))
  } catch {
    return { index: emptyExtensionIndex(), writable: true }
  }
  if (bytes.byteLength > MAX_INDEX_BYTES) return degraded(fs, 'exceeds the size cap')
  let value: unknown
  try {
    value = JSON.parse(new TextDecoder().decode(bytes))
  } catch {
    return degraded(fs, 'is not valid JSON')
  }
  const parsed = parseExtensionIndex(value)
  if (parsed.ok) return { index: parsed.index, writable: true }
  if (parsed.reason === 'newer') {
    fs.warn('[extensions] index.json has a newer schema_version; leaving it untouched')
    return { index: emptyExtensionIndex(), writable: false }
  }
  return degraded(fs, 'failed validation')
}

/** Atomic write under 0700 dirs (home re-tightened, as localState does). */
export function writeExtensionIndex(index: ExtensionIndex, fs: ExtensionFs): void {
  const home = join(fs.homedir(), SOLUS_HOME_DIRNAME)
  const root = extensionsRoot(fs.homedir())
  fs.mkdir(root, EXTENSION_DIR_MODE)
  fs.chmod(home, SOLUS_HOME_MODE)
  fs.chmod(root, EXTENSION_DIR_MODE)
  const target = indexPath(fs)
  const temp = `${target}.${fs.tempSuffix()}.tmp`
  fs.writeFile(temp, `${JSON.stringify(index, null, 2)}\n`, EXTENSION_FILE_MODE)
  try {
    fs.rename(temp, target)
  } catch (error) {
    fs.remove(temp)
    throw error
  }
}

/** Upsert one id. False — writing nothing — for an unsafe id or a read-only index. */
export function upsertInstalled(id: string, entry: InstalledExtension, fs: ExtensionFs): boolean {
  if (!isSafeExtensionId(id)) return false
  const { index, writable } = readExtensionIndex(fs)
  if (!writable) return false
  const installed: Record<string, InstalledExtension> = Object.assign(
    Object.create(null),
    index.installed,
    { [id]: entry }
  )
  writeExtensionIndex({ ...index, installed }, fs)
  return true
}

/** Drop one id. Absent is a success (the goal state holds). */
export function removeInstalled(id: string, fs: ExtensionFs): boolean {
  if (!isSafeExtensionId(id)) return false
  const { index, writable } = readExtensionIndex(fs)
  if (!(id in index.installed)) return true
  if (!writable) return false
  const installed: Record<string, InstalledExtension> = Object.assign(
    Object.create(null),
    index.installed
  )
  delete installed[id]
  writeExtensionIndex({ ...index, installed }, fs)
  return true
}
