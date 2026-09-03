// SOLUSDEV-235 / EXT-05 — the `solus-ext://<id>/<version>/<path>` scheme
// (ADR-035 §1): the read-only origin an extension iframe loads its bundle from.
//
// Every segment is validated (id slug, strict semver or the literal `dev`,
// contract-shaped path with a served suffix); the file is resolved against the
// installed bundle directory — or, for `dev`, the registered unpacked folder —
// and refused when its REALPATH escapes that root. Only a fixed suffix set is
// served, each with a fixed content type; html carries the ADR-035 CSP. Any
// failure is a 404 and the handler never throws (a protocol handler that
// throws takes the renderer's frame down with it).
//
// index.ts registers the scheme as privileged BEFORE app ready and installs
// the handler AFTER; this module has no Electron import so it is fully
// unit-testable.
import { isSafeBundlePath, isSafeExtensionId } from '@solus/shared-types'
import { BUNDLE_LIMITS } from './bundleInstall'
import { safeDevFolder } from './devExtensions'
import type { ExtensionFs } from './extensionFs'
import { readExtensionIndex, type InstalledExtension } from './extensionIndex'
import {
  bundleDir,
  DEV_VERSION,
  extensionsRoot,
  isSafeExtensionVersion,
  resolveInsideRoot
} from './extensionPaths'

export const EXT_SCHEME = 'solus-ext'

/** Passed to protocol.registerSchemesAsPrivileged before app ready. `standard`
 *  gives the scheme an origin (so `'self'` in the CSP means the bundle),
 *  `secure` lets it hold the sandboxed frame; fetch and CORS stay OFF — the
 *  bridge is the only way out of a frame. */
export const EXT_SCHEME_PRIVILEGES = {
  standard: true,
  secure: true,
  supportFetchAPI: false,
  corsEnabled: false
} as const

/** The ONLY suffixes served, each with a fixed content type — the bundle
 *  validator caps the same set server-side. */
export const EXT_CONTENT_TYPES: Readonly<Record<string, string>> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
  '.md': 'text/markdown; charset=utf-8'
}
const SERVED_SUFFIXES = Object.keys(EXT_CONTENT_TYPES)

/** ADR-035 §1: no network from the frame, no remote script, no nested frames. */
export const EXT_HTML_CSP =
  "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; " +
  "img-src 'self' data:; font-src 'self'; connect-src 'none'; frame-src 'none'; " +
  "object-src 'none'; base-uri 'none'; form-action 'none'"

export interface ExtUrlParts {
  readonly id: string
  readonly version: string
  readonly path: string
}

function decodeSegment(segment: string): string | null {
  try {
    return decodeURIComponent(segment)
  } catch {
    return null
  }
}

/** `solus-ext://<id>/<version>/<path>` → parts, or null for anything else. */
export function parseExtUrl(url: string): ExtUrlParts | null {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return null
  }
  if (parsed.protocol !== `${EXT_SCHEME}:` || parsed.username || parsed.password || parsed.port)
    return null
  const id = parsed.hostname
  if (!isSafeExtensionId(id)) return null
  const [, rawVersion, ...rawPath] = parsed.pathname.split('/')
  const version = rawVersion === undefined ? null : decodeSegment(rawVersion)
  if (version === null || !(version === DEV_VERSION || isSafeExtensionVersion(version))) return null
  // Decode each segment, then re-validate the JOINED path: an encoded `/` or
  // `..` must fail the shape check, not slip past it.
  const segments = rawPath.map(decodeSegment)
  if (segments.some((s) => s === null || s.includes('/'))) return null
  const path = segments.join('/')
  if (!isSafeBundlePath(path, SERVED_SUFFIXES)) return null
  return { id, version, path }
}

export interface ExtResponse {
  readonly status: number
  readonly headers: Readonly<Record<string, string>>
  readonly body: Uint8Array | null
}

const NOT_FOUND: ExtResponse = {
  status: 404,
  headers: { 'content-type': 'text/plain; charset=utf-8', 'x-content-type-options': 'nosniff' },
  body: null
}

/** The directory `parts` is served from: the cached bundle for a registry
 *  install at exactly its installed version, or the re-validated devPath for a
 *  dev registration under the literal `dev` version. Null otherwise. */
function assetRoot(
  parts: ExtUrlParts,
  entry: InstalledExtension | undefined,
  fs: ExtensionFs
): string | null {
  if (entry === undefined) return null
  if (parts.version === DEV_VERSION) {
    return entry.source === 'dev' ? safeDevFolder(entry.devPath, fs) : null
  }
  if (entry.source !== 'registry' || entry.version !== parts.version) return null
  return bundleDir(extensionsRoot(fs.homedir()), parts.id, parts.version)
}

function contentTypeFor(path: string): string {
  const lowered = path.toLowerCase()
  const suffix = SERVED_SUFFIXES.find((s) => lowered.endsWith(s)) as string
  return EXT_CONTENT_TYPES[suffix]
}

function found(path: string, body: Uint8Array): ExtResponse {
  const contentType = contentTypeFor(path)
  const headers: Record<string, string> = {
    'content-type': contentType,
    'content-length': String(body.byteLength),
    'x-content-type-options': 'nosniff'
  }
  if (contentType.startsWith('text/html')) headers['content-security-policy'] = EXT_HTML_CSP
  return { status: 200, headers, body }
}

/** Resolve and read one asset. Never throws: every failure is the 404. */
export function serveExtAsset(url: string, fs: ExtensionFs): ExtResponse {
  try {
    const parts = parseExtUrl(url)
    if (parts === null) return NOT_FOUND
    const root = assetRoot(parts, readExtensionIndex(fs).index.installed[parts.id], fs)
    if (root === null) return NOT_FOUND
    const real = resolveInsideRoot(root, parts.path, fs.realpath)
    if (real === null) return NOT_FOUND
    const size = fs.fileSize(real)
    if (size === null || size > BUNDLE_LIMITS.bytes) return NOT_FOUND
    return found(parts.path, fs.readFile(real))
  } catch (error) {
    fs.warn(
      `[extensions] protocol request failed: ${error instanceof Error ? error.message : error}`
    )
    return NOT_FOUND
  }
}

/** The fetch-shaped Response Electron's protocol.handle expects. */
export function toResponse(res: ExtResponse): Response {
  return new Response(res.body === null ? null : new Uint8Array(res.body), {
    status: res.status,
    headers: res.headers
  })
}

/** `protocol.handle(EXT_SCHEME, createExtProtocolHandler(fs))` — after app ready. */
export function createExtProtocolHandler(fs: ExtensionFs): (request: { url: string }) => Response {
  return (request) => toResponse(serveExtAsset(request.url, fs))
}
