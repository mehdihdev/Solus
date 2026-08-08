// Local project folder + git clone (SOLUSDEV-164). Tests the security-critical
// pure logic: repo-URL validation, clone-target derivation, and the clone
// orchestration (argument-list git invocation, never a shell string — CLAUDE.md
// §7 subprocess rules). The spawn itself is injected so we assert the exact
// argument vector and result mapping without touching the real git binary.
import { describe, it, expect, vi } from 'vitest'
import { isValidRepoUrl, cloneTargetName, cloneRepo, vscodeFolderUrl } from './projectFolder'

describe('isValidRepoUrl', () => {
  it('accepts https, ssh, and scp-style git URLs', () => {
    expect(isValidRepoUrl('https://github.com/octo/arm-v2.git')).toBe(true)
    expect(isValidRepoUrl('ssh://git@github.com/octo/arm-v2.git')).toBe(true)
    expect(isValidRepoUrl('git@github.com:octo/arm-v2.git')).toBe(true)
  })

  it('rejects empty, flag-like, whitespace, and unsupported-scheme URLs', () => {
    expect(isValidRepoUrl('')).toBe(false)
    expect(isValidRepoUrl('   ')).toBe(false)
    expect(isValidRepoUrl('--upload-pack=evil')).toBe(false)
    expect(isValidRepoUrl('https://github.com/octo/a b')).toBe(false)
    expect(isValidRepoUrl('file:///etc/passwd')).toBe(false)
    expect(isValidRepoUrl('ext::sh -c whoami')).toBe(false)
  })
})

describe('cloneTargetName', () => {
  it('derives a safe directory name from the repo URL', () => {
    expect(cloneTargetName('https://github.com/octo/arm-v2.git')).toBe('arm-v2')
    expect(cloneTargetName('git@github.com:octo/Rover_MK2.git')).toBe('Rover_MK2')
    expect(cloneTargetName('https://gitlab.com/team/sub/proj')).toBe('proj')
  })

  it('falls back to a default name when the segment sanitizes to nothing', () => {
    expect(cloneTargetName('https://github.com/octo/@@@')).toBe('repo')
  })
})

describe('vscodeFolderUrl', () => {
  it('builds a vscode://file URL from an absolute path', () => {
    expect(vscodeFolderUrl('/home/u/arm')).toBe('vscode://file/home/u/arm')
  })

  it('percent-encodes path segments', () => {
    expect(vscodeFolderUrl('/home/u/my robot #2')).toBe('vscode://file/home/u/my%20robot%20%232')
  })

  it('handles Windows-style paths', () => {
    expect(vscodeFolderUrl('C:\\Users\\u\\arm')).toBe('vscode://file/C%3A/Users/u/arm')
  })

  it('rejects empty and relative paths', () => {
    expect(vscodeFolderUrl('')).toBeNull()
    expect(vscodeFolderUrl('   ')).toBeNull()
    expect(vscodeFolderUrl('relative/path')).toBeNull()
  })
})

describe('cloneRepo', () => {
  const okRun = vi.fn(async () => ({ code: 0, stderr: '' }))

  it('rejects an invalid repo URL before spawning', async () => {
    const run = vi.fn(async () => ({ code: 0, stderr: '' }))
    const res = await cloneRepo(
      { repoUrl: '--evil', parentDir: '/home/u/code' },
      { run, exists: () => true }
    )
    expect(res).toHaveProperty('error')
    expect(run).not.toHaveBeenCalled()
  })

  it('refuses a non-existent parent directory', async () => {
    const res = await cloneRepo(
      { repoUrl: 'https://github.com/octo/arm.git', parentDir: '/nope' },
      { run: okRun, exists: () => false }
    )
    expect(res).toHaveProperty('error')
  })

  it('refuses to overwrite an existing target directory', async () => {
    const res = await cloneRepo(
      { repoUrl: 'https://github.com/octo/arm.git', parentDir: '/home/u/code' },
      { run: okRun, exists: (p: string) => p.endsWith('arm') || p === '/home/u/code' }
    )
    expect(res).toHaveProperty('error')
  })

  it('invokes git with an argument list guarded by -- and returns the path', async () => {
    const run = vi.fn(async () => ({ code: 0, stderr: '' }))
    const res = await cloneRepo(
      { repoUrl: 'https://github.com/octo/arm.git', parentDir: '/home/u/code' },
      { run, exists: (p: string) => p === '/home/u/code' }
    )
    expect(run).toHaveBeenCalledTimes(1)
    const [args, cwd] = run.mock.calls[0] as unknown as [string[], string]
    expect(args).toEqual(['clone', '--', 'https://github.com/octo/arm.git', '/home/u/code/arm'])
    expect(cwd).toBe('/home/u/code')
    expect(res).toEqual({ path: '/home/u/code/arm' })
  })

  it('surfaces a git failure as an error', async () => {
    const run = vi.fn(async () => ({ code: 128, stderr: 'fatal: repository not found' }))
    const res = await cloneRepo(
      { repoUrl: 'https://github.com/octo/missing.git', parentDir: '/home/u/code' },
      { run, exists: (p: string) => p === '/home/u/code' }
    )
    expect(res).toEqual({ error: 'fatal: repository not found' })
  })
})
