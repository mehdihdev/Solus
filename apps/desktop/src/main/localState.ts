// The ~/.solus project registry, main-process side (SOLUSDEV-166 / ADR-034).
//
// This is the machine-local source of truth for project→working-copy links.
// The renderer's projectFolderStore (localStorage) is a display cache that
// write-throughs here over IPC; the companion's workspace env derives from
// THIS file at spawn — which is what closes the Altium fail-closed gap
// (docs/CAPABILITIES.md: SOLUS_COMPANION_WORKSPACE "read in two places,
// written nowhere").
//
// Contract: docs/contracts/local-state.md — JSON only, schema_version, atomic
// temp+replace writes, 0700 home, no secrets ever (MCP forks can read HOME),
// and a file written by a NEWER schema version is read-only for us.
//
// The fs surface is injected (companionEnv.ts idiom) so every decision here is
// unit-testable without a real filesystem.
import {
  emptyProjectRegistry,
  isSafeProjectId,
  parseProjectRegistry,
  PROJECTS_FILENAME,
  SOLUS_HOME_DIRNAME,
  SOLUS_HOME_MODE,
  type ProjectFolderLink,
  type ProjectRegistry
} from '@solus/shared-types'
import { randomBytes } from 'node:crypto'
import {
  chmodSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync
} from 'node:fs'
import { homedir } from 'node:os'
import { isAbsolute, join, parse as parsePath, relative } from 'node:path'

/** Registry files hold private machine paths — owner read/write only. */
const REGISTRY_FILE_MODE = 0o600

/** Cap on projects.json — read on every companion spawn and folder:links call.
 *  A registry is tiny (a path per project); anything past this is corruption or
 *  an attempt to make a reader chew megabytes (cf. the companion's 32 KiB stdin
 *  cap). Over it, degrade to empty like any other invalid file. */
const MAX_REGISTRY_BYTES = 1024 * 1024

/** Control characters (NUL included) are banned everywhere: NUL makes
 *  `child_process.spawn` throw, and a newline corrupts the env line. */
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\x00-\x1f]/

/**
 * Characters additionally banned on Windows (SOLUSDEV-166 security review C1).
 * The workspace is exported as SOLUS_COMPANION_WORKSPACE and the Windows
 * `launch.cmd` fork twin interpolates it into a cmd.exe line BEFORE parsing, so
 * `" & ^ | < > %` are command separators there. The POSIX `bin/launch` quotes
 * the value under `env -i`, so these are safe on macOS/Linux and legal in real
 * directory names (`R&D`, `100% done`) — banning them there would wrongly
 * refuse folders a user actually picked. Glob chars `* ?` are never valid in a
 * real path on any platform, but only matter for the cmd.exe sink.
 */
const WINDOWS_UNSAFE_PATH_CHARS = /["<>|&^%!*?]/

export interface LocalStateDeps {
  homedir: () => string
  /** Read a whole file as UTF-8; throws when missing/unreadable. */
  readFile: (path: string) => string
  writeFile: (path: string, content: string, mode: number) => void
  /** Move `from` over `to`, replacing it — atomic on POSIX. */
  replaceFile: (from: string, to: string) => void
  /** Create the directory (parents included) with the given mode. */
  mkdir: (path: string, mode: number) => void
  chmod: (path: string, mode: number) => void
  /** Whether `path` exists and is a directory — a workspace must be a real
   *  directory the user chose, not a file or a phantom. */
  isDirectory: (path: string) => boolean
  /** Canonical absolute path (symlinks + `.`/`..` resolved), or null when it
   *  does not exist. The value we validate and store, so a `..`/symlink dodge
   *  cannot land somewhere other than what was checked. */
  realpath: (path: string) => string | null
  /** The platform whose path rules apply — injected so the win32 branch is
   *  testable off Windows. */
  platform: NodeJS.Platform
  /** Best-effort delete (temp cleanup). */
  remove: (path: string) => void
  /** Unpredictable suffix for the temp file name. */
  tempSuffix: () => string
  now: () => Date
  /** Non-fatal diagnostics (a corrupt registry is worth a line, not a crash). */
  warn: (message: string) => void
}

export function solusHomePath(deps: Pick<LocalStateDeps, 'homedir'>): string {
  return join(deps.homedir(), SOLUS_HOME_DIRNAME)
}

function projectsFilePath(deps: LocalStateDeps): string {
  return join(solusHomePath(deps), PROJECTS_FILENAME)
}

export interface RegistryRead {
  registry: ProjectRegistry
  /** False when the file was written by a NEWER schema version — we must not
   *  rewrite it (docs/contracts/local-state.md rule 6). */
  writable: boolean
}

/** Re-run the credential stripper over every entry as it comes off disk, so a
 *  registry written before the write-time sanitizer (or hand-edited) never
 *  hands a live token back to the renderer through folder:links (review H2-c).
 *  Preserves the null-prototype map from parseProjects. */
function sanitizeRegistryOnRead(registry: ProjectRegistry): ProjectRegistry {
  const projects: Record<string, ProjectFolderLink> = Object.create(null)
  for (const [projectId, link] of Object.entries(registry.projects)) {
    const repoUrl = link.repoUrl !== undefined ? sanitizeRepoUrl(link.repoUrl) : undefined
    projects[projectId] = {
      path: link.path,
      ...(repoUrl !== undefined ? { repoUrl } : {}),
      ...(link.lastOpenedAt !== undefined ? { lastOpenedAt: link.lastOpenedAt } : {})
    }
  }
  return { ...registry, projects }
}

/** Read `~/.solus/projects.json`, degrading — never throwing — per contract:
 *  missing/corrupt ⇒ empty and writable; newer ⇒ empty and READ-ONLY. */
export function readRegistry(deps: LocalStateDeps): RegistryRead {
  let raw: string
  try {
    raw = deps.readFile(projectsFilePath(deps))
  } catch {
    return { registry: emptyProjectRegistry(), writable: true } // fresh machine
  }
  if (raw.length > MAX_REGISTRY_BYTES) {
    deps.warn('[local-state] projects.json exceeds the size cap; treating as empty')
    return { registry: emptyProjectRegistry(), writable: true }
  }
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    deps.warn('[local-state] projects.json is not valid JSON; treating as empty')
    return { registry: emptyProjectRegistry(), writable: true }
  }
  const parsed = parseProjectRegistry(value)
  if (parsed.ok) return { registry: sanitizeRegistryOnRead(parsed.registry), writable: true }
  if (parsed.reason === 'newer') {
    deps.warn('[local-state] projects.json has a newer schema_version; leaving it untouched')
    return { registry: emptyProjectRegistry(), writable: false }
  }
  deps.warn('[local-state] projects.json failed validation; treating as empty')
  return { registry: emptyProjectRegistry(), writable: true }
}

export type AtomicWriteDeps = Pick<LocalStateDeps, 'writeFile' | 'replaceFile' | 'remove' | 'tempSuffix'>

/** Atomic write: a fresh temp file beside the target (created with `mode`,
 *  under an unpredictable name), then replaced over it. The target is never
 *  opened for writing, so a pre-planted symlink at `target` is replaced, not
 *  followed. Shared by the registry and the companion id (machineIdentity.ts). */
export function writeFileAtomically(
  target: string,
  content: string,
  mode: number,
  deps: AtomicWriteDeps
): void {
  const temp = `${target}.${deps.tempSuffix()}.tmp`
  deps.writeFile(temp, content, mode)
  try {
    deps.replaceFile(temp, target)
  } catch (error) {
    deps.remove(temp) // never leave temp litter behind a failed replace
    throw error
  }
}

/** Atomic write of the registry. The home dir is created 0700 — and
 *  re-chmodded, tightening a pre-existing dir created with default umask by
 *  older companion builds (ADR-034 consequence). */
function writeRegistry(registry: ProjectRegistry, deps: LocalStateDeps): void {
  const home = solusHomePath(deps)
  deps.mkdir(home, SOLUS_HOME_MODE)
  deps.chmod(home, SOLUS_HOME_MODE)
  const target = projectsFilePath(deps)
  writeFileAtomically(target, `${JSON.stringify(registry, null, 2)}\n`, REGISTRY_FILE_MODE, deps)
}

/** Case-fold for path identity: POSIX is case-sensitive, macOS/Windows are not,
 *  so a `/USERS/me` variant must still match `/home` on those platforms. */
function foldPath(path: string, deps: LocalStateDeps): string {
  const trimmed = path.replace(/[/\\]+$/, '') || path
  return deps.platform === 'linux' ? trimmed : trimmed.toLowerCase()
}

/** Whether `child` is `parent` or nested under it (both already canonical). */
function isAtOrUnder(parent: string, child: string, deps: LocalStateDeps): boolean {
  const rel = relative(foldPath(parent, deps), foldPath(child, deps))
  return rel === '' || (!rel.startsWith('..') && !isAbsolute(rel))
}

/**
 * The canonical form of a path safe to hand a fork as its workspace root, or
 * null (SOLUSDEV-166 security review C1). Applied at BOTH the write boundary
 * and the read boundary, because the registry file is itself untrusted — forks
 * run as the user and can write ~/.solus, and a legacy/hand-edited file may
 * hold anything.
 *
 * Rejects: control characters anywhere; the cmd.exe metacharacter class on
 * Windows; anything that does not resolve to a real directory; and — after
 * canonicalizing symlinks and `.`/`..` — the filesystem root, the user's home,
 * and ~/.solus or anything beneath it (which would hand a fork the registry
 * and every other project's private paths). Returns the CANONICAL path so the
 * stored value is exactly what was validated.
 */
/** The raw-string half of the check: shape + dangerous characters, before any
 *  filesystem access. */
function hasSafePathShape(path: string, deps: LocalStateDeps): boolean {
  if (path.length === 0 || !isAbsolute(path) || CONTROL_CHARS.test(path)) return false
  return !(deps.platform === 'win32' && WINDOWS_UNSAFE_PATH_CHARS.test(path))
}

function safeWorkspacePath(path: string, deps: LocalStateDeps): string | null {
  if (!hasSafePathShape(path, deps)) return null
  const real = deps.realpath(path)
  if (real === null || !deps.isDirectory(real)) return null
  if (foldPath(real, deps) === foldPath(parsePath(real).root, deps)) return null // any fs / drive root
  // Reject the home directory AND every ancestor of it (`/`, `/Users`,
  // `/home`, …): each CONTAINS ~/.solus, so a fork confined there could still
  // reach the registry and other projects' private paths (review C1-a final).
  if (isAtOrUnder(real, deps.homedir(), deps)) return null
  if (isAtOrUnder(solusHomePath(deps), real, deps)) return null // ~/.solus and its subtree
  return real
}

/**
 * Strip any embedded credentials from a repo URL before it is persisted or
 * returned to the renderer — the registry is fork-readable, so a
 * `https://oauth2:TOKEN@host/…` clone URL must not leave a live token on disk
 * (SOLUSDEV-166 security review H2, ADR-034 rule 5). For an http(s) URL both
 * username and password are dropped (GitHub PATs ride as the username); for
 * ssh/git the username (`git`) is required to clone, so only a password is
 * dropped. A value that is not a proper `//`-authority URL but still embeds a
 * `:secret@` is dropped entirely (it is only informational); a credential-free
 * scp-style `git@host:path` is kept verbatim.
 */
function sanitizeRepoUrl(repoUrl: string): string | undefined {
  const trimmed = repoUrl.trim()
  let url: URL | null = null
  try {
    url = new URL(trimmed)
  } catch {
    url = null
  }
  if (url && url.host) {
    if (url.protocol === 'http:' || url.protocol === 'https:') url.username = ''
    url.password = ''
    return url.toString()
  }
  // Opaque-scheme (`oauth2:TOKEN@host`), scp-style, or junk: keep only if it
  // carries no `:secret@` credential segment.
  return /:[^@\s/]*@/.test(trimmed) ? undefined : trimmed
}

/**
 * Upsert one project's folder link. Returns false — writing nothing — for
 * invalid input or a registry owned by a newer schema version.
 */
export function linkProjectFolder(
  projectId: string,
  link: { path: string; repoUrl?: string },
  deps: LocalStateDeps
): boolean {
  if (!isSafeProjectId(projectId)) return false
  const canonicalPath = safeWorkspacePath(link.path, deps)
  if (canonicalPath === null) return false
  const repoUrl = link.repoUrl !== undefined ? sanitizeRepoUrl(link.repoUrl) : undefined
  const entry: ProjectFolderLink = {
    path: canonicalPath,
    ...(repoUrl !== undefined ? { repoUrl } : {}),
    lastOpenedAt: deps.now().toISOString()
  }
  const { registry, writable } = readRegistry(deps)
  if (!writable) return false
  writeRegistry({ ...registry, projects: { ...registry.projects, [projectId]: entry } }, deps)
  return true
}

/** Remove one project's link. Absent is a success (the goal state holds). */
export function unlinkProjectFolder(projectId: string, deps: LocalStateDeps): boolean {
  if (!isSafeProjectId(projectId)) return false
  const { registry, writable } = readRegistry(deps)
  if (!(projectId in registry.projects)) return true
  if (!writable) return false
  const projects = { ...registry.projects }
  delete projects[projectId]
  writeRegistry({ ...registry, projects }, deps)
  return true
}

export interface FolderLinkInput {
  path: string
  repoUrl?: string
}

/** Validate untrusted renderer input for the folder:link IPC channel. Picks
 *  ONLY the known fields — extra renderer properties never reach the registry.
 *  Null means invalid; deeper checks (absolute path, safe id) stay in
 *  linkProjectFolder. */
export function folderLinkInput(value: unknown): FolderLinkInput | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const { path, repoUrl } = value as Record<string, unknown>
  if (typeof path !== 'string' || path.length === 0) return null
  if (repoUrl !== undefined && typeof repoUrl !== 'string') return null
  return { path, ...(repoUrl !== undefined ? { repoUrl } : {}) }
}

/** The working-copy path for a project, or null — what the companion spawn
 *  feeds into SOLUS_COMPANION_WORKSPACE. The stored value is RE-VALIDATED here
 *  (review C1-b): the registry file is fork-writable and may be hand-edited or
 *  predate the write-time checks, so the sink cannot trust what it reads. A
 *  path that no longer passes (deleted directory, hostile edit) yields null,
 *  and the fork fails closed rather than confining somewhere unsafe. */
export function projectWorkspace(projectId: string | null, deps: LocalStateDeps): string | null {
  if (projectId === null || !isSafeProjectId(projectId)) return null
  const stored = readRegistry(deps).registry.projects[projectId]?.path
  if (stored === undefined) return null
  const safe = safeWorkspacePath(stored, deps)
  if (safe === null) deps.warn('[local-state] stored workspace failed validation; ignoring it')
  return safe
}

/** Production deps: node fs/os/crypto. `replaceFile` falls back to
 *  remove-then-rename for Windows, where rename won't replace. */
export const realLocalStateDeps: LocalStateDeps = {
  homedir,
  readFile: (path) => readFileSync(path, 'utf8'),
  writeFile: (path, content, mode) => writeFileSync(path, content, { mode }),
  replaceFile: (from, to) => {
    try {
      renameSync(from, to)
    } catch (error) {
      if (process.platform !== 'win32') throw error
      rmSync(to, { force: true })
      renameSync(from, to)
    }
  },
  mkdir: (path, mode) => {
    mkdirSync(path, { recursive: true, mode })
  },
  chmod: (path, mode) => {
    if (process.platform !== 'win32') chmodSync(path, mode)
  },
  isDirectory: (path) => {
    try {
      return statSync(path).isDirectory()
    } catch {
      return false
    }
  },
  realpath: (path) => {
    try {
      return realpathSync.native(path)
    } catch {
      return null
    }
  },
  platform: process.platform,
  remove: (path) => {
    rmSync(path, { force: true })
  },
  tempSuffix: () => randomBytes(6).toString('hex'),
  now: () => new Date(),
  warn: (message) => console.warn(message)
}
