// The environment the companion child needs — CAD-02.
//
// Extracted as pure functions so the derivation is testable without spawning a
// process, and because getting it wrong is invisible: the companion validates
// its own config and exits, and `spawnChild` restarts it forever with the error
// discarded. That is precisely how Fusion stayed unreachable.
//
// The companion enforces two rules (`companion/config.py`), and both exist for
// a reason worth preserving:
//   1. `wss://` only — `ws://` is tolerated solely for loopback.
//   2. the host must be in `SOLUS_COMPANION_ALLOWED_HOSTS`, because that host
//      is where the user's bearer token gets sent. A redirected companion
//      posting a token to an attacker is what the allowlist prevents.

import { dirname, join } from 'node:path'

/** Hosts a companion may always dial: the local dev API. */
const LOOPBACK_HOSTS = ['localhost', '127.0.0.1'] as const

/** A project id is a path SEGMENT here. It arrives from the renderer, so
 *  anything with a slash, a dot-segment or an escape is refused outright rather
 *  than silently redirecting the companion's dial target. */
const SAFE_PROJECT_ID = /^[A-Za-z0-9_-]+$/

/** The vendored MCP tree, relative to the repo root. Same name the packaged
 *  companion looks for beside its binary (`config.py` `_PACKAGED_TREE`). */
const INTEGRATIONS_TREE = ['integrations', 'mcp'] as const

/**
 * Locate the vendored MCP tree by walking up from `startDir`.
 *
 * The companion's own fallback (`config.py` `default_integrations_root`) looks
 * beside `sys.executable`, which is the packaged binary in production and
 * `.venv/bin/python3` in dev — so in dev it always returns None and the
 * companion exits with `SOLUS_COMPANION_INTEGRATIONS_ROOT is required` on every
 * spawn. That is a crash loop whose only UI symptom is a bridge pill reading
 * "offline", which is the same invisible-failure shape as the URL above.
 *
 * Walks rather than counting directory hops: `app.getAppPath()` is
 * `<repo>/apps/desktop` under `pnpm dev`, but can be a build output directory,
 * and a hardcoded `../..` would quietly resolve to nothing.
 *
 * `exists` is injected so this stays pure and unit-testable, like the rest of
 * this module. Returns null when no ancestor holds the tree — the caller must
 * then leave the variable unset rather than invent a path.
 */
export function findIntegrationsRoot(
  startDir: string,
  exists: (path: string) => boolean
): string | null {
  return findAncestorPath(startDir, INTEGRATIONS_TREE, exists)
}

/** The first `<ancestor>/<segments…>` that exists, walking up from `startDir`
 *  to the filesystem root; null when none does. Shared by the MCP tree and the
 *  dev drive helper (SOLUSDEV-319). */
export function findAncestorPath(
  startDir: string,
  segments: readonly string[],
  exists: (path: string) => boolean
): string | null {
  let dir = startDir
  for (;;) {
    const candidate = join(dir, ...segments)
    if (exists(candidate)) return candidate
    const parent = dirname(dir)
    if (parent === dir) return null // filesystem root — stop, never loop
    dir = parent
  }
}

/**
 * The bridge WebSocket URL for a given API base, or null when it cannot be
 * derived. Throws for a non-loopback `http://` base rather than emitting a
 * `ws://` URL the companion will reject — a loud failure here beats a silent
 * restart loop later.
 */
export function companionWsUrl(apiBaseUrl: string, projectId: string | null): string | null {
  if (!apiBaseUrl.trim()) return null
  // No project selected is a normal state at app start. Absent beats a URL the
  // server will reject: the route is project-scoped, so a project-less URL
  // matches nothing and every retry answers 403.
  if (!projectId || !SAFE_PROJECT_ID.test(projectId)) return null
  let url: URL
  try {
    url = new URL(apiBaseUrl)
  } catch {
    return null
  }
  const loopback = (LOOPBACK_HOSTS as readonly string[]).includes(url.hostname)
  if (url.protocol === 'http:' && !loopback) {
    throw new Error(
      `Companion requires wss://; refusing to derive a bridge URL from insecure ${apiBaseUrl}`
    )
  }
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  // MUST be `/api/v1/projects/{id}/bridge`. This used to be `<base>/bridge`,
  // with a comment claiming the companion appended the project segment itself.
  // It does the reverse — `_BRIDGE_PATH_RE` in companion/config.py parses the
  // project id OUT of this URL — so the dial target matched no route on the
  // API, Starlette answered 403, and the bridge never once connected.
  url.pathname = `${url.pathname.replace(/\/$/, '')}/projects/${projectId}/bridge`
  return url.toString()
}

/**
 * The child's environment: everything inherited, plus the two variables the
 * companion cannot start without.
 *
 * An explicit `SOLUS_COMPANION_URL` in the inherited environment wins, so a
 * build can be pointed at another API without a code change. When no URL can be
 * derived the variable is left ABSENT rather than set to something malformed —
 * the companion's own "SOLUS_COMPANION_URL is required" is the actionable
 * message, and a broken value would replace it with a confusing one.
 */
export interface CompanionEnvOptions {
  /** Vendored MCP tree for a dev run; null in a packaged build. */
  integrationsRoot?: string | null
  /** The project this companion serves. The bridge URL is project-scoped, so
   *  without one there is no URL to derive and the companion stays idle. */
  projectId?: string | null
  /** The project's working copy on this machine, from the ~/.solus registry
   *  (SOLUSDEV-166 / ADR-034). Null when the project has no linked folder —
   *  the variable is then left ABSENT so workspace-gated forks (Altium) fail
   *  closed rather than confining to an arbitrary directory. */
  workspace?: string | null
  /** SOLUSDEV-319 (sol-drive.md §5): true only while "SOL can use your mouse
   *  and keyboard" is on AND driving is available for this project. The
   *  companion then reaches the helper through the agent, with the session
   *  main sends on stdin (slice 3b) — there is no helper path variable. */
  drive?: boolean
  /** ADR-041 amendment 2026-10-28 (H-1): a packaged build starts from
   *  PACKAGED_ENV_ALLOWLIST instead of inheriting everything, so inherited
   *  SOLUS_COMPANION_* and PYTHON* (and DYLD_*, NODE_OPTIONS …) never reach the
   *  companion. Dev keeps inheriting (developer overrides). */
  packaged?: boolean
}

/** What a packaged companion may inherit; LC_* is matched by prefix. */
export const PACKAGED_ENV_ALLOWLIST = ['PATH', 'HOME', 'USER', 'LOGNAME', 'TMPDIR', 'LANG'] as const

function allowlisted(
  inherited: Record<string, string | undefined>
): Record<string, string | undefined> {
  const allowed = new Set<string>(PACKAGED_ENV_ALLOWLIST)
  return Object.fromEntries(
    Object.entries(inherited).filter(([key]) => allowed.has(key) || key.startsWith('LC_'))
  )
}

export function companionEnv(
  inherited: Record<string, string | undefined>,
  apiBaseUrl: string,
  options: CompanionEnvOptions = {}
): Record<string, string | undefined> {
  const env = options.packaged ? allowlisted(inherited) : { ...inherited }
  // Third of the same kind. Absent when nothing resolved, on purpose: the
  // companion refuses to invent a default because "that would turn a packaging
  // mistake into a silent zero-server run" (config.py), and a guessed path here
  // would replace its actionable error with exactly that.
  if (!env.SOLUS_COMPANION_INTEGRATIONS_ROOT && options.integrationsRoot) {
    env.SOLUS_COMPANION_INTEGRATIONS_ROOT = options.integrationsRoot
  }
  if (!env.SOLUS_COMPANION_URL) {
    const url = companionWsUrl(apiBaseUrl, options.projectId ?? null)
    if (url) env.SOLUS_COMPANION_URL = url
  }
  // Fourth of the same kind (see CAPABILITIES.md: "read in two places, written
  // nowhere"). Same rules as its siblings: an explicit inherited value wins,
  // and nothing resolved means ABSENT, never empty.
  if (!env.SOLUS_COMPANION_WORKSPACE && options.workspace) {
    env.SOLUS_COMPANION_WORKSPACE = options.workspace
  }
  applyDrive(env, options)
  if (!env.SOLUS_COMPANION_ALLOWED_HOSTS) {
    env.SOLUS_COMPANION_ALLOWED_HOSTS = allowedHosts(env.SOLUS_COMPANION_URL)
  }
  return env
}

/** The drive switch is NOT like its siblings: the setting is the consent, so
 *  an inherited value never wins — it is deleted unless the option says on.
 *  It also stays off when the workspace the child gets is not the folder the
 *  nested-folder rule checked (an inherited override). The slice 3 helper path
 *  variable is retired (3b) and always removed. */
function applyDrive(env: Record<string, string | undefined>, options: CompanionEnvOptions): void {
  delete env.SOLUS_COMPANION_DRIVE
  delete env.SOLUS_DRIVE_HELPER
  if (options.drive !== true || !options.workspace) return
  if (env.SOLUS_COMPANION_WORKSPACE !== options.workspace) return
  env.SOLUS_COMPANION_DRIVE = '1'
}

/** The workspace a child built from these inputs would drive in — exactly
 *  the env builder's decision (null: drive off). Main bakes and compares this
 *  (L6), so what the relay accepts as `--within` is what the child got. */
export function companionDriveWorkspace(
  inherited: Record<string, string | undefined>,
  options: Pick<CompanionEnvOptions, 'workspace' | 'drive' | 'packaged'>
): string | null {
  const env = companionEnv(inherited, '', options)
  return env.SOLUS_COMPANION_DRIVE === '1' ? (options.workspace ?? null) : null
}

/** Loopback always, plus the configured URL's host when it parses. */
function allowedHosts(configuredUrl: string | undefined): string {
  const hosts = new Set<string>(LOOPBACK_HOSTS)
  if (configuredUrl) {
    try {
      hosts.add(new URL(configuredUrl).hostname)
    } catch {
      /* a malformed override is the companion's to report, not ours */
    }
  }
  return [...hosts].join(',')
}
