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
  parseProjectRegistry,
  PROJECT_ID_RE,
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
  renameSync,
  rmSync,
  statSync,
  writeFileSync
} from 'node:fs'
import { homedir } from 'node:os'
import { isAbsolute, join } from 'node:path'

/** Registry files hold private machine paths — owner read/write only. */
const REGISTRY_FILE_MODE = 0o600

/** Cap on projects.json — read on every companion spawn and folder:links call.
 *  A registry is tiny (a path per project); anything past this is corruption or
 *  an attempt to make a reader chew megabytes (cf. the companion's 32 KiB stdin
 *  cap). Over it, degrade to empty like any other invalid file. */
const MAX_REGISTRY_BYTES = 1024 * 1024

/**
 * Characters banned from a workspace path (SOLUSDEV-166 security review C1/M4).
 * This value is persisted, then exported as SOLUS_COMPANION_WORKSPACE and
 * consumed by each MCP fork's `bin/launch` — the Windows `launch.cmd` twin
 * interpolates it into a cmd.exe line before parsing, so `" & ^ | < > %` there
 * are command separators. Control characters (NUL included) additionally make
 * `child_process.spawn` throw, and glob chars never appear in a real directory
 * path. A dialog-chosen path never contains these; only a forged IPC value can.
 */
// eslint-disable-next-line no-control-regex
const UNSAFE_PATH_CHARS = /[\x00-\x1f"<>|&^%!*?]/

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
  /** Best-effort delete (temp cleanup). */
  remove: (path: string) => void
  /** Unpredictable suffix for the temp file name. */
  tempSuffix: () => string
  now: () => Date
  /** Non-fatal diagnostics (a corrupt registry is worth a line, not a crash). */
  warn: (message: string) => void
}

export function solusHomePath(deps: LocalStateDeps): string {
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
  if (parsed.ok) return { registry: parsed.registry, writable: true }
  if (parsed.reason === 'newer') {
    deps.warn('[local-state] projects.json has a newer schema_version; leaving it untouched')
    return { registry: emptyProjectRegistry(), writable: false }
  }
  deps.warn('[local-state] projects.json failed validation; treating as empty')
  return { registry: emptyProjectRegistry(), writable: true }
}

/** Atomic write: temp file in the same directory, then replace. The home dir
 *  is created 0700 — and re-chmodded, tightening a pre-existing dir created
 *  with default umask by older companion builds (ADR-034 consequence). */
function writeRegistry(registry: ProjectRegistry, deps: LocalStateDeps): void {
  const home = solusHomePath(deps)
  deps.mkdir(home, SOLUS_HOME_MODE)
  deps.chmod(home, SOLUS_HOME_MODE)
  const target = projectsFilePath(deps)
  const temp = `${target}.${deps.tempSuffix()}.tmp`
  deps.writeFile(temp, `${JSON.stringify(registry, null, 2)}\n`, REGISTRY_FILE_MODE)
  try {
    deps.replaceFile(temp, target)
  } catch (error) {
    deps.remove(temp) // never leave temp litter behind a failed replace
    throw error
  }
}

/** Trailing-separator-normalized path, for identity comparisons. */
function normalizePath(path: string): string {
  return path.replace(/[/\\]+$/, '') || path
}

/**
 * Whether a path is safe to persist and hand to a fork as its workspace root
 * (SOLUSDEV-166 security review C1). It must be an absolute, real directory,
 * carry no shell/control characters, and not be a location that would give a
 * fork sweeping reach — the filesystem root, the user's home, or ~/.solus
 * itself. The path normally comes from the OS folder dialog; these checks exist
 * to defeat a forged IPC value.
 */
function isSafeWorkspacePath(path: string, deps: LocalStateDeps): boolean {
  if (path.length === 0 || !isAbsolute(path) || UNSAFE_PATH_CHARS.test(path)) return false
  const normalized = normalizePath(path)
  const forbidden = new Set([deps.homedir(), solusHomePath(deps), '/'].map(normalizePath))
  if (forbidden.has(normalized)) return false
  return deps.isDirectory(path)
}

/**
 * Strip any embedded credentials from a repo URL before it is persisted — the
 * registry is fork-readable, so a `https://oauth2:TOKEN@host/…` clone URL must
 * not leave a live token on disk (SOLUSDEV-166 security review H2, ADR-034
 * rule 5). scp-style `git@host:path` URLs carry no password by shape and are
 * kept; anything that parses as a URL is rebuilt without userinfo; an
 * unparseable value that still smells of `:secret@` is dropped (it is only
 * informational).
 */
function sanitizeRepoUrl(repoUrl: string): string | undefined {
  try {
    const url = new URL(repoUrl)
    url.username = ''
    url.password = ''
    return url.toString()
  } catch {
    return /:[^@/]*@/.test(repoUrl) ? undefined : repoUrl
  }
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
  if (!PROJECT_ID_RE.test(projectId) || !isSafeWorkspacePath(link.path, deps)) return false
  const repoUrl = link.repoUrl !== undefined ? sanitizeRepoUrl(link.repoUrl) : undefined
  const entry: ProjectFolderLink = {
    path: link.path,
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
  if (!PROJECT_ID_RE.test(projectId)) return false
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
 *  feeds into SOLUS_COMPANION_WORKSPACE. */
export function projectWorkspace(projectId: string | null, deps: LocalStateDeps): string | null {
  if (projectId === null || !PROJECT_ID_RE.test(projectId)) return null
  return readRegistry(deps).registry.projects[projectId]?.path ?? null
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
  remove: (path) => {
    rmSync(path, { force: true })
  },
  tempSuffix: () => randomBytes(6).toString('hex'),
  now: () => new Date(),
  warn: (message) => console.warn(message)
}
