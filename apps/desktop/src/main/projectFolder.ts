// Local project folder + git clone for the main process (SOLUSDEV-164).
//
// Security (CLAUDE.md §7 subprocess rules): git is invoked with an ARGUMENT
// LIST, never a shell string — no `shell: true`, so shell metacharacters in a
// repo URL cannot execute. The URL is additionally validated (scheme allowlist,
// no whitespace, no leading `-`) and passed after a `--` separator so it can
// never be read as a git flag. The clone target is derived from a sanitized
// basename and must not already exist. The heavy lifting (spawn) is injected as
// `run` so the guard logic is unit-tested without the real binary.
import { spawn } from 'child_process'
import { existsSync } from 'fs'
import { join } from 'path'

/** Allowed git URL shapes: https(s), ssh://, and scp-style `user@host:path`. */
const HTTPS_URL = /^https?:\/\/[^\s]+$/
const SSH_URL = /^ssh:\/\/[^\s]+$/
const SCP_URL = /^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:[^\s]+$/

/** Whether a string is a git remote URL we are willing to clone. Pure. */
export function isValidRepoUrl(url: string): boolean {
  const u = url.trim()
  if (!u || u.startsWith('-') || /\s/.test(u)) return false
  return HTTPS_URL.test(u) || SSH_URL.test(u) || SCP_URL.test(u)
}

/** Derive a safe target directory name from a repo URL. Pure. */
export function cloneTargetName(url: string): string {
  const withoutGit = url
    .trim()
    .replace(/\.git$/, '')
    .replace(/\/+$/, '')
  const tail = withoutGit.split(/[/:]/).pop() ?? ''
  const safe = tail.replace(/[^A-Za-z0-9_.-]/g, '')
  return safe || 'repo'
}

/** Build a `vscode://file/...` URL for an absolute folder path. Pure; returns
 *  null for anything non-absolute — only a path we can vouch for is safe to
 *  hand to the OS URL handler. Segments are percent-encoded so spaces/#/? in
 *  folder names cannot break or extend the URL. */
export function vscodeFolderUrl(path: string): string | null {
  const p = path.trim()
  const isAbsolute = p.startsWith('/') || /^[A-Za-z]:[\\/]/.test(p)
  if (!p || !isAbsolute) return null
  const encoded = p.split(/[\\/]/).filter(Boolean).map(encodeURIComponent).join('/')
  return `vscode://file/${encoded}`
}

export interface CloneInput {
  repoUrl: string
  parentDir: string
}

export type CloneResult = { path: string } | { error: string }

export interface CloneDeps {
  /** Run git with the given argument list in `cwd`; resolves exit code + stderr. */
  run: (args: string[], cwd: string) => Promise<{ code: number; stderr: string }>
  exists: (path: string) => boolean
}

/** Clone `repoUrl` into a new subdirectory of `parentDir`. Validated + guarded. */
export async function cloneRepo(input: CloneInput, deps: CloneDeps): Promise<CloneResult> {
  const repoUrl = input.repoUrl.trim()
  if (!isValidRepoUrl(repoUrl))
    return { error: 'That does not look like a valid git repository URL.' }
  if (!input.parentDir || !deps.exists(input.parentDir)) {
    return { error: 'Choose an existing folder to clone into.' }
  }
  const target = join(input.parentDir, cloneTargetName(repoUrl))
  if (deps.exists(target)) {
    return { error: `A folder named "${cloneTargetName(repoUrl)}" already exists here.` }
  }
  try {
    const { code, stderr } = await deps.run(['clone', '--', repoUrl, target], input.parentDir)
    if (code === 0) return { path: target }
    return { error: stderr.trim() || `git clone exited with code ${code}.` }
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error)
    return { error: message.includes('ENOENT') ? 'git is not installed or not on PATH.' : message }
  }
}

/** Ten minutes: a generous ceiling so a large clone completes but a hung one
 *  cannot run forever (CLAUDE.md §7 — timeouts on external work). */
const CLONE_TIMEOUT_MS = 10 * 60 * 1000

/** Real spawn-based git runner (thin glue; the logic above is what's tested). */
function runGit(args: string[], cwd: string): Promise<{ code: number; stderr: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn('git', args, { cwd, timeout: CLONE_TIMEOUT_MS })
    let stderr = ''
    child.stderr?.on('data', (chunk) => {
      stderr += String(chunk)
    })
    child.on('error', reject)
    child.on('close', (code) => resolve({ code: code ?? 1, stderr }))
  })
}

/** Production dependencies for cloneRepo. */
export const cloneDeps: CloneDeps = { run: runGit, exists: existsSync }
