// SOLUSDEV-329 — main's re-probe of an interpreter the renderer chose
// (docs/architecture/mcp-fork-runtime.md §3 step 1, §9 `mcpRuntime:choose`).
//
// The CLI has no "probe this one path" subcommand, so main runs the same kind
// of fixed, isolated probe itself before saving a choice: argv only, `-I`,
// no shell, a from-scratch env, a timeout and a tiny output cap. The output is
// untrusted and parsed strictly; nothing from it but the version is kept.
import type { RuntimeErrorCode } from './protocol'

export const PROBE_CODE =
  'import json,platform,sys;' +
  'print(json.dumps({"implementation":platform.python_implementation().lower(),' +
  '"version":"%d.%d.%d"%sys.version_info[:3]}))'

const PROBE_TIMEOUT_MS = 10_000
const PROBE_MAX_BUFFER = 4096
/** A fixed system PATH (§3): nothing inherited reaches the probe. */
const PROBE_ENV: Record<string, string> =
  process.platform === 'win32'
    ? // CPython on Windows cannot seed its hash randomization without SYSTEMROOT.
      { PATH: 'C:\\Windows\\System32', SYSTEMROOT: process.env.SystemRoot ?? 'C:\\Windows' }
    : { PATH: '/usr/bin:/bin' }
const STORE_ALIAS_RE = /[\\/]WindowsApps[\\/]python[^\\/]*\.exe$/i
const VERSION_RE = /^3\.(1[23])\.\d+$/

export type SupportedMinor = '3.12' | '3.13'

export type ProbeResult =
  | { ok: true; version: string; minor: SupportedMinor }
  | { ok: false; error_code: RuntimeErrorCode }

export interface ProbeDeps {
  execFile: (
    file: string,
    args: string[],
    options: {
      shell: false
      timeout: number
      maxBuffer: number
      env: Record<string, string>
      windowsHide: true
    }
  ) => Promise<{ stdout: string }>
  /** Canonical path, or null when it does not exist. */
  realpath: (path: string) => string | null
  isFile: (path: string) => boolean
}

const fail = (error_code: RuntimeErrorCode): ProbeResult => ({ ok: false, error_code })

function parseProbe(stdout: string): ProbeResult {
  let raw: unknown
  try {
    raw = JSON.parse(stdout.trim())
  } catch {
    return fail('python_probe_failed')
  }
  if (typeof raw !== 'object' || raw === null) return fail('python_probe_failed')
  const { implementation, version } = raw as Record<string, unknown>
  if (typeof implementation !== 'string' || typeof version !== 'string') {
    return fail('python_probe_failed')
  }
  if (!/^\d+\.\d+\.\d+$/.test(version)) return fail('python_probe_failed')
  if (implementation !== 'cpython') return fail('python_not_cpython')
  const match = VERSION_RE.exec(version)
  if (!match) return fail('python_unsupported_version')
  return { ok: true, version, minor: `3.${match[1]}` as SupportedMinor }
}

export async function probeInterpreter(path: string, deps: ProbeDeps): Promise<ProbeResult> {
  const real = deps.realpath(path)
  if (STORE_ALIAS_RE.test(path) || (real !== null && STORE_ALIAS_RE.test(real))) {
    return fail('python_store_alias')
  }
  if (real === null || !deps.isFile(real)) return fail('python_probe_failed')
  try {
    const { stdout } = await deps.execFile(path, ['-I', '-c', PROBE_CODE], {
      shell: false,
      timeout: PROBE_TIMEOUT_MS,
      maxBuffer: PROBE_MAX_BUFFER,
      env: { ...PROBE_ENV },
      windowsHide: true
    })
    return parseProbe(stdout)
  } catch {
    return fail('python_probe_failed')
  }
}
