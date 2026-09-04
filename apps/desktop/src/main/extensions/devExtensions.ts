// SOLUSDEV-235 / EXT-05 — developer mode (ADR-035 §4): an unpacked extension
// folder anywhere on disk, served in place at solus-ext://<id>/dev/… and never
// published. The registration persists in index.json (source 'dev' + devPath)
// and is re-validated on every load.
//
// The folder becomes a protocol root, so the same reach rules as a companion
// workspace apply (localState.safeWorkspacePath): never the filesystem root,
// never the home directory or an ancestor of it, never ~/.solus or anything
// beneath it — each would let an extension URL read the user's private files.
import {
  EXTENSION_MANIFEST_FILENAME,
  isSafeExtensionId,
  SOLUS_HOME_DIRNAME,
  type ExtensionManifest
} from '@solus/shared-types'
import { isAbsolute, join, parse as parsePath } from 'node:path'
import { sha256Hex } from './bundleInstall'
import type { ExtensionFs } from './extensionFs'
import {
  readExtensionIndex,
  removeInstalled,
  upsertInstalled,
  type InstalledExtension
} from './extensionIndex'
import { isAtOrUnder } from './extensionPaths'
import { loadManifestFromBytes, MAX_MANIFEST_BYTES } from './manifestToml'

export type DevLoadResult =
  | { readonly ok: true; readonly manifest: ExtensionManifest; readonly devPath: string }
  | { readonly ok: false; readonly problems: readonly string[] }

// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\x00-\x1f]/

function problems(...list: string[]): DevLoadResult {
  return { ok: false, problems: list }
}

/** The canonical folder path when it is safe to serve from, else null. */
export function safeDevFolder(path: unknown, fs: ExtensionFs): string | null {
  if (typeof path !== 'string' || path.length === 0 || !isAbsolute(path)) return null
  if (CONTROL_CHARS.test(path)) return null
  const real = fs.realpath(path)
  if (real === null || !fs.isDirectory(real)) return null
  if (real === parsePath(real).root) return null
  if (isAtOrUnder(real, fs.homedir())) return null // home and every ancestor of it
  if (isAtOrUnder(join(fs.homedir(), SOLUS_HOME_DIRNAME), real)) return null
  return real
}

type ManifestRead = { bytes: Uint8Array } | { problem: string }

function readManifestFile(folder: string, fs: ExtensionFs): ManifestRead {
  const path = join(folder, EXTENSION_MANIFEST_FILENAME)
  const size = fs.fileSize(path)
  if (size === null)
    return { problem: 'extension.toml: missing (must be a regular file at the folder root)' }
  if (size > MAX_MANIFEST_BYTES)
    return { problem: `extension.toml: exceeds ${MAX_MANIFEST_BYTES} bytes` }
  try {
    return { bytes: fs.readFile(path) }
  } catch {
    return { problem: 'extension.toml: unreadable' }
  }
}

/** Validate an unpacked folder and record it as the dev entry for its id. */
export function loadDevExtension(path: unknown, fs: ExtensionFs): DevLoadResult {
  const folder = safeDevFolder(path, fs)
  if (folder === null)
    return problems(
      'path: must be an existing directory that is not the filesystem root, your home folder (or an ancestor of it), or ~/.solus'
    )
  const read = readManifestFile(folder, fs)
  if ('problem' in read) return problems(read.problem)
  const loaded = loadManifestFromBytes(read.bytes)
  if (!loaded.ok) return { ok: false, problems: loaded.problems }
  const entry: InstalledExtension = {
    version: loaded.manifest.extension.version,
    contentHash: sha256Hex(read.bytes),
    installedAt: fs.now().toISOString(),
    source: 'dev',
    devPath: folder
  }
  if (!upsertInstalled(loaded.manifest.extension.id, entry, fs))
    return problems('index: ~/.solus/extensions/index.json is read-only (written by a newer Solus)')
  return { ok: true, manifest: loaded.manifest, devPath: folder }
}

/** Forget a dev registration. Registry installs are not touched — that is
 *  uninstallExtension's job — and a read-only index refuses. */
export function removeDevExtension(id: string, fs: ExtensionFs): { ok: boolean } {
  if (!isSafeExtensionId(id)) return { ok: false }
  const { index, writable } = readExtensionIndex(fs)
  if (!writable) return { ok: false }
  const entry = index.installed[id]
  if (entry === undefined) return { ok: true }
  if (entry.source !== 'dev') return { ok: false }
  return { ok: removeInstalled(id, fs) }
}
