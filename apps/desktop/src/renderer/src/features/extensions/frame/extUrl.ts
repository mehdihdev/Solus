// SOLUSDEV-235 / EXT-13 — the ONE place the renderer spells a bundle URL
// (extensions-runtime.md §5): `solus-ext://<id>/<version>/<entry>`. Every
// segment is validated with the same rules main's protocol handler applies, so
// a manifest entry that main would 404 is refused here first and the frame
// shows an honest error instead of a blank iframe. Main owns the handler; this
// module only produces URLs and has no Electron import.
import { isSafeBundlePath, isSafeExtensionId } from '@solus/shared-types'

export const EXT_SCHEME = 'solus-ext'
/** The `<version>` segment a developer registration is served under (§7). */
export const DEV_VERSION = 'dev'

/** Mirrors main's EXT_CONTENT_TYPES keys — the only suffixes the handler serves. */
export const EXT_SERVED_SUFFIXES: readonly string[] = [
  '.html',
  '.js',
  '.css',
  '.json',
  '.svg',
  '.png',
  '.webp',
  '.woff2',
  '.md'
]

// Strict semver, as main/extensions/extensionPaths.ts (a renderer module cannot
// import that file: it pulls node:path).
const SEMVER_RE = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?$/
const MAX_VERSION_LENGTH = 64

export function isSafeExtVersion(version: string): boolean {
  return (
    version === DEV_VERSION || (version.length <= MAX_VERSION_LENGTH && SEMVER_RE.test(version))
  )
}

export interface ExtUrlOptions {
  /** Dev-mode reload nonce (`?r=<n>`, ignored by the handler — §7). */
  readonly nonce?: number
}

/**
 * `solus-ext://<id>/<version>/<entry>`, or null when any part fails the
 * handler's rules (id slug, semver | `dev`, contract-shaped path with a served
 * suffix). Null is a caller error to surface, never a URL to try anyway.
 */
export function extEntryUrl(
  id: string,
  version: string,
  entry: string,
  options: ExtUrlOptions = {}
): string | null {
  if (!isSafeExtensionId(id) || !isSafeExtVersion(version)) return null
  if (!isSafeBundlePath(entry, EXT_SERVED_SUFFIXES)) return null
  const path = entry.split('/').map(encodeURIComponent).join('/')
  const query = options.nonce === undefined ? '' : `?r=${Math.max(0, Math.floor(options.nonce))}`
  return `${EXT_SCHEME}://${id}/${encodeURIComponent(version)}/${path}${query}`
}
