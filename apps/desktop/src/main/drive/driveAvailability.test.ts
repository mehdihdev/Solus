// SOLUSDEV-319 drive slice 3 (sol-drive.md §5): when driving may run for the
// active project — the order of the reasons, and the nested-folder rule
// (security review M1 of M2/M3) compared after realpath by whole segment.
import { describe, expect, it } from 'vitest'
import { driveUnavailable, isAtOrInside, nestedFolderConflict } from './driveAvailability'

const identity = (p: string): string => p

describe('isAtOrInside', () => {
  it('compares whole path segments, never string prefixes', () => {
    expect(isAtOrInside('/a/b', '/a/b', 'darwin')).toBe(true)
    expect(isAtOrInside('/a/b/c', '/a/b', 'darwin')).toBe(true)
    expect(isAtOrInside('/a/bc', '/a/b', 'darwin')).toBe(false)
    expect(isAtOrInside('/a', '/a/b', 'darwin')).toBe(false)
  })

  it('ignores trailing separators', () => {
    expect(isAtOrInside('/a/b/', '/a/b', 'darwin')).toBe(true)
    expect(isAtOrInside('/a/b/c', '/a/b///', 'darwin')).toBe(true)
  })

  it('folds case on macOS (case-insensitive by default), not on linux', () => {
    expect(isAtOrInside('/Users/Me/Rover', '/users/me', 'darwin')).toBe(true)
    expect(isAtOrInside('/Users/Me/Rover', '/users/me', 'linux')).toBe(false)
  })
})

describe('nestedFolderConflict', () => {
  const folders = {
    outer: '/w/robots',
    inner: '/w/robots/arm',
    other: '/w/drone',
    sib: '/w/robotsx'
  }

  it('flags an active folder that contains another project folder', () => {
    expect(nestedFolderConflict('outer', folders, identity, 'darwin')).toBe(true)
  })

  it('flags an active folder inside another project folder', () => {
    expect(nestedFolderConflict('inner', folders, identity, 'darwin')).toBe(true)
  })

  it('flags two projects linked to the same folder', () => {
    expect(nestedFolderConflict('a', { a: '/w/x', b: '/w/x' }, identity, 'darwin')).toBe(true)
  })

  it('passes disjoint folders, a segment-prefix sibling included', () => {
    expect(nestedFolderConflict('other', folders, identity, 'darwin')).toBe(false)
    expect(
      nestedFolderConflict('sib', { sib: '/w/robotsx', o: '/w/robots' }, identity, 'darwin')
    ).toBe(false)
  })

  it('compares after realpath, so a symlinked link cannot dodge the rule', () => {
    const real = (p: string): string | null => (p === '/link/to/arm' ? '/w/robots/arm' : p)
    expect(nestedFolderConflict('o', { o: '/w/robots', l: '/link/to/arm' }, real, 'darwin')).toBe(
      true
    )
  })

  it('an unresolvable OTHER folder is ignored; an unresolvable active folder fails closed', () => {
    const real = (p: string): string | null => (p === '/gone' ? null : p)
    expect(nestedFolderConflict('a', { a: '/w/a', g: '/gone' }, real, 'darwin')).toBe(false)
    expect(nestedFolderConflict('g', { a: '/w/a', g: '/gone' }, real, 'darwin')).toBe(true)
  })
})

describe('driveUnavailable', () => {
  const base = {
    platform: 'darwin' as NodeJS.Platform,
    helperOk: true,
    projectId: 'p' as string | null,
    folders: { p: '/w/p' } as Record<string, string>,
    realpath: identity
  }

  it('is null when every condition holds', () => {
    expect(driveUnavailable(base)).toBeNull()
  })

  it('bundle_modified after no_helper and before the folder reasons (review HIGH-1)', () => {
    expect(driveUnavailable({ ...base, bundleOk: false, projectId: null })).toBe('bundle_modified')
    expect(driveUnavailable({ ...base, helperOk: false, bundleOk: false })).toBe('no_helper')
    expect(driveUnavailable({ ...base, bundleOk: true })).toBeNull()
  })

  it('checks in order: not_macos → no_helper → no_folder → nested_folder', () => {
    const nested = { p: '/w/p', q: '/w/p/q' }
    expect(driveUnavailable({ ...base, platform: 'linux', helperOk: false, projectId: null })).toBe(
      'not_macos'
    )
    expect(driveUnavailable({ ...base, helperOk: false, projectId: null })).toBe('no_helper')
    expect(driveUnavailable({ ...base, projectId: null })).toBe('no_folder')
    expect(driveUnavailable({ ...base, folders: {} })).toBe('no_folder')
    expect(driveUnavailable({ ...base, folders: nested })).toBe('nested_folder')
  })
})
