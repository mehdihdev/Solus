// SOLUSDEV-329 — main re-probes an interpreter the renderer chose
// (docs/architecture/mcp-fork-runtime.md §3 step 1, §9 `mcpRuntime:choose`).
import { describe, expect, it, vi } from 'vitest'
import { PROBE_CODE, probeInterpreter, type ProbeDeps } from './probe'

function deps(stdout: string, over: Partial<ProbeDeps> = {}): ProbeDeps {
  return {
    execFile: vi.fn(async () => ({ stdout })),
    realpath: (p) => p,
    isFile: () => true,
    ...over
  }
}

const out = (implementation: string, version: string): string =>
  `${JSON.stringify({ implementation, version })}\n`

describe('probeInterpreter', () => {
  it('accepts CPython 3.12 and 3.13 and reports the minor version', async () => {
    await expect(
      probeInterpreter('/usr/bin/python3.12', deps(out('cpython', '3.12.7')))
    ).resolves.toEqual({
      ok: true,
      version: '3.12.7',
      minor: '3.12'
    })
    await expect(
      probeInterpreter('/usr/local/bin/python3.13', deps(out('cpython', '3.13.1')))
    ).resolves.toMatchObject({ ok: true, minor: '3.13' })
  })

  it('runs the fixed probe isolated, argv only, with a scrubbed env and bounds', async () => {
    const d = deps(out('cpython', '3.12.1'))
    await probeInterpreter('/opt/py/bin/python3', d)
    expect(d.execFile).toHaveBeenCalledWith(
      '/opt/py/bin/python3',
      ['-I', '-c', PROBE_CODE],
      expect.objectContaining({
        shell: false,
        timeout: expect.any(Number),
        maxBuffer: expect.any(Number)
      })
    )
    const env = (vi.mocked(d.execFile).mock.calls[0][2] as { env: Record<string, string> }).env
    expect(Object.keys(env).filter((k) => /^(PYTHON|PIP_|VIRTUAL_ENV|CONDA_)/.test(k))).toEqual([])
  })

  it('refuses an unsupported version', async () => {
    await expect(
      probeInterpreter('/usr/bin/python3', deps(out('cpython', '3.11.9')))
    ).resolves.toEqual({
      ok: false,
      error_code: 'python_unsupported_version'
    })
  })

  it('refuses PyPy', async () => {
    await expect(probeInterpreter('/opt/pypy3', deps(out('pypy', '3.12.0')))).resolves.toEqual({
      ok: false,
      error_code: 'python_not_cpython'
    })
  })

  it('refuses the Microsoft Store alias without running it', async () => {
    const d = deps(out('cpython', '3.12.7'))
    const alias = 'C:\\Users\\dev\\AppData\\Local\\Microsoft\\WindowsApps\\python.exe'
    await expect(probeInterpreter(alias, d)).resolves.toEqual({
      ok: false,
      error_code: 'python_store_alias'
    })
    expect(d.execFile).not.toHaveBeenCalled()
  })

  it('refuses a missing file, a failed run and garbage output as probe failures', async () => {
    const failed = { ok: false, error_code: 'python_probe_failed' }
    await expect(probeInterpreter('/nope', deps('', { isFile: () => false }))).resolves.toEqual(
      failed
    )
    await expect(
      probeInterpreter(
        '/x',
        deps('', { execFile: vi.fn(async () => Promise.reject(new Error('boom'))) })
      )
    ).resolves.toEqual(failed)
    await expect(probeInterpreter('/x', deps('hello'))).resolves.toEqual(failed)
    await expect(probeInterpreter('/x', deps(out('cpython', '3.12')))).resolves.toEqual(failed)
  })
})
