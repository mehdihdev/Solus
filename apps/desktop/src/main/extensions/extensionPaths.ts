// SOLUSDEV-235 / EXT-05 — where extension bundles live and how a URL segment
// becomes a path without ever leaving the cache (ADR-035 §4, ADR-034 Layer 1).
//
//   ~/.solus/extensions/index.json            the installed set
//   ~/.solus/extensions/<id>/<version>/…      one extracted bundle
//
// Ids come from the contract (isSafeExtensionId); versions are strict semver so
// a version can never be a dot-segment or a separator; entry names reuse the
// contract's bundle-path shape. Containment is decided on REALPATHS so a
// symlink planted inside a bundle cannot point the protocol at the user's disk.
import { isSafeBundlePath, SOLUS_HOME_DIRNAME } from '@solus/shared-types'
import { isAbsolute, join, relative } from 'node:path'

export const EXTENSIONS_DIRNAME = 'extensions'
export const EXTENSIONS_INDEX_FILENAME = 'index.json'
/** The `<version>` segment a developer-mode entry is served under. */
export const DEV_VERSION = 'dev'

const EXTENSION_VERSION_RE = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?$/
/** Semver prerelease tags are unbounded by grammar; a folder name is not. */
const MAX_VERSION_LENGTH = 64

export function isSafeExtensionVersion(version: string): boolean {
  return version.length <= MAX_VERSION_LENGTH && EXTENSION_VERSION_RE.test(version)
}

/** The contract's path rule minus the suffix check (`endsWith('')` is always
 *  true): relative, no `..`/`.`, no backslash, safe segment charset, ≤ 200. */
export function isSafeBundleEntryName(name: string): boolean {
  return isSafeBundlePath(name, [''])
}

export function extensionsRoot(home: string): string {
  return join(home, SOLUS_HOME_DIRNAME, EXTENSIONS_DIRNAME)
}

export function bundleDir(root: string, id: string, version: string): string {
  return join(root, id, version)
}

/** Whether `child` is `parent` or nested under it — both already canonical. */
export function isAtOrUnder(parent: string, child: string): boolean {
  const rel = relative(parent, child)
  return rel === '' || (!rel.startsWith('..') && !isAbsolute(rel))
}

/**
 * The canonical on-disk path of `relPath` inside `root`, or null when either
 * does not exist or the file's realpath escapes the root's realpath (symlink
 * or dot-segment dodge). The relative path must already be a safe entry name.
 */
export function resolveInsideRoot(
  root: string,
  relPath: string,
  realpath: (path: string) => string | null
): string | null {
  const realRoot = realpath(root)
  if (realRoot === null) return null
  const real = realpath(join(root, relPath))
  if (real === null || !isAtOrUnder(realRoot, real)) return null
  return real
}
