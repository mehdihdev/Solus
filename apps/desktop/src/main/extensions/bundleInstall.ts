// SOLUSDEV-235 / EXT-05 — the bundle installer (ADR-035 §4, ADR-034 amendment
// 2026-09-03). The registry hands the renderer zip bytes plus the hash it
// published; THIS process re-derives the hash, refuses on mismatch, and only
// then extracts — bounded in file count and bytes, refusing symlinks, unsafe
// names and duplicates — into a temp directory under the cache root that is
// renamed into <root>/<id>/<version>/ as the last step. Any refusal or failure
// leaves the cache exactly as it was. Bundles are static assets: nothing here
// executes them.
import {
  EXTENSION_MANIFEST_FILENAME,
  isSafeExtensionId,
  MANIFEST_LIMITS
} from '@solus/shared-types'
import { createHash } from 'node:crypto'
import { dirname, join } from 'node:path'
import { EXTENSION_DIR_MODE, EXTENSION_FILE_MODE, type ExtensionFs } from './extensionFs'
import {
  isSha256Hex,
  readExtensionIndex,
  removeInstalled,
  upsertInstalled,
  type InstalledExtension
} from './extensionIndex'
import {
  bundleDir,
  extensionsRoot,
  isSafeBundleEntryName,
  isSafeExtensionVersion
} from './extensionPaths'
import { loadManifestFromBytes, MAX_MANIFEST_BYTES } from './manifestToml'
import {
  openZip,
  ZipEntryTooLargeError,
  ZipReadError,
  type OpenZip,
  type ZipArchive,
  type ZipEntryInfo
} from './zipReader'

export const BUNDLE_LIMITS = {
  /** Extracted bytes per bundle (the contract's cap). */
  bytes: MANIFEST_LIMITS.bundleBytes,
  files: 2000
} as const

export type InstallError =
  | 'invalid_input'
  | 'hash_mismatch'
  | 'too_large'
  | 'zip_invalid'
  | 'too_many_entries'
  | 'unsafe_entry'
  | 'symlink_entry'
  | 'manifest_missing'
  | 'manifest_invalid'
  | 'manifest_mismatch'
  | 'index_readonly'
  | 'write_failed'

export interface InstallRequest {
  readonly id: string
  readonly version: string
  /** sha256 hex of the zip bytes, as published by the registry. */
  readonly contentHash: string
  readonly bytes: Uint8Array
}

export type InstallResult =
  | { readonly ok: true }
  | { readonly ok: false; readonly error: InstallError; readonly problems?: readonly string[] }

type Refusal = Exclude<InstallResult, { ok: true }>

function refuse(error: InstallError, problems?: readonly string[]): Refusal {
  return { ok: false, error, ...(problems ? { problems } : {}) }
}

export function sha256Hex(bytes: Uint8Array): string {
  return createHash('sha256').update(bytes).digest('hex')
}

function checkRequest(req: InstallRequest): Refusal | null {
  const hash = req.contentHash.toLowerCase()
  if (!isSafeExtensionId(req.id) || !isSafeExtensionVersion(req.version) || !isSha256Hex(hash))
    return refuse('invalid_input')
  if (req.bytes.byteLength > BUNDLE_LIMITS.bytes) return refuse('too_large')
  if (sha256Hex(req.bytes) !== hash) return refuse('hash_mismatch')
  return null
}

/** Decide on the listing BEFORE inflating anything. */
function planFiles(entries: readonly ZipEntryInfo[]): { files: ZipEntryInfo[] } | Refusal {
  const files = entries.filter((e) => !e.isDirectory)
  if (files.length > BUNDLE_LIMITS.files) return refuse('too_many_entries')
  const seen = new Set<string>()
  let total = 0
  for (const file of files) {
    if (file.isSymlink) return refuse('symlink_entry')
    if (file.isEncrypted || seen.has(file.name) || !isSafeBundleEntryName(file.name))
      return refuse('unsafe_entry')
    seen.add(file.name)
    total += file.declaredSize
    if (total > BUNDLE_LIMITS.bytes) return refuse('too_large')
  }
  if (!seen.has(EXTENSION_MANIFEST_FILENAME)) return refuse('manifest_missing')
  return { files }
}

async function checkManifest(archive: ZipArchive, req: InstallRequest): Promise<Refusal | null> {
  let bytes: Uint8Array
  try {
    bytes = await archive.read(EXTENSION_MANIFEST_FILENAME, MAX_MANIFEST_BYTES)
  } catch {
    return refuse('manifest_invalid', ['extension.toml: unreadable or too large'])
  }
  const loaded = loadManifestFromBytes(bytes)
  if (!loaded.ok) return refuse('manifest_invalid', loaded.problems)
  const { id, version } = loaded.manifest.extension
  return id === req.id && version === req.version ? null : refuse('manifest_mismatch')
}

async function extractTo(
  dir: string,
  archive: ZipArchive,
  files: readonly ZipEntryInfo[],
  fs: ExtensionFs
): Promise<void> {
  let remaining: number = BUNDLE_LIMITS.bytes
  fs.mkdir(dir, EXTENSION_DIR_MODE)
  for (const file of files) {
    const bytes = await archive.read(file.name, remaining)
    remaining -= bytes.byteLength
    const target = join(dir, file.name)
    fs.mkdir(dirname(target), EXTENSION_DIR_MODE)
    fs.writeFile(target, bytes, EXTENSION_FILE_MODE)
  }
}

/** Rename the extracted tree into place, dropping the previous cached
 *  version of the same id (installs pin ONE version per extension). */
function commit(
  tempDir: string,
  req: InstallRequest,
  previous: InstalledExtension | undefined,
  fs: ExtensionFs
): void {
  const root = extensionsRoot(fs.homedir())
  const target = bundleDir(root, req.id, req.version)
  fs.mkdir(join(root, req.id), EXTENSION_DIR_MODE)
  fs.remove(target)
  fs.rename(tempDir, target)
  if (previous?.source === 'registry' && previous.version !== req.version)
    fs.remove(bundleDir(root, req.id, previous.version))
}

function failureKind(error: unknown): InstallError {
  if (error instanceof ZipEntryTooLargeError) return 'too_large'
  return error instanceof ZipReadError ? 'zip_invalid' : 'write_failed'
}

/** Verify → plan → validate manifest → extract to temp → rename → record. */
export async function installBundle(
  req: InstallRequest,
  fs: ExtensionFs,
  open: OpenZip = openZip
): Promise<InstallResult> {
  const bad = checkRequest(req)
  if (bad) return bad
  const { index, writable } = readExtensionIndex(fs)
  if (!writable) return refuse('index_readonly')
  let archive: ZipArchive
  try {
    archive = await open(req.bytes)
  } catch {
    return refuse('zip_invalid')
  }
  const plan = planFiles(archive.entries)
  if ('ok' in plan) return plan
  const manifestBad = await checkManifest(archive, req)
  if (manifestBad) return manifestBad

  const root = extensionsRoot(fs.homedir())
  const tempDir = join(root, `.tmp-${req.id}-${fs.tempSuffix()}`)
  try {
    fs.mkdir(root, EXTENSION_DIR_MODE)
    await extractTo(tempDir, archive, plan.files, fs)
    commit(tempDir, req, index.installed[req.id], fs)
  } catch (error) {
    fs.remove(tempDir)
    const detail = error instanceof Error ? error.message : String(error)
    fs.warn(`[extensions] install of ${req.id}@${req.version} failed: ${detail}`)
    return refuse(failureKind(error))
  }
  const entry: InstalledExtension = {
    version: req.version,
    contentHash: req.contentHash.toLowerCase(),
    installedAt: fs.now().toISOString(),
    source: 'registry'
  }
  return upsertInstalled(req.id, entry, fs) ? { ok: true } : refuse('index_readonly')
}

/** Remove every cached version of `id` and its index entry. A read-only index
 *  refuses everything — a newer Solus owns those files. */
export function uninstallExtension(id: string, fs: ExtensionFs): { ok: boolean } {
  if (!isSafeExtensionId(id)) return { ok: false }
  if (!readExtensionIndex(fs).writable || !removeInstalled(id, fs)) return { ok: false }
  fs.remove(join(extensionsRoot(fs.homedir()), id))
  return { ok: true }
}
