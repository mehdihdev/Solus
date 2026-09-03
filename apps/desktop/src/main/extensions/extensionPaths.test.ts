// SOLUSDEV-235 / EXT-05 — path discipline for ~/.solus/extensions.
import { describe, expect, test } from 'vitest'
import {
  bundleDir,
  extensionsRoot,
  isAtOrUnder,
  isSafeBundleEntryName,
  isSafeExtensionVersion,
  resolveInsideRoot
} from './extensionPaths'

describe('isSafeExtensionVersion', () => {
  test.each(['1.0.0', '0.0.1', '10.20.30', '1.2.0-beta.1', '2.0.0-rc-1'])('accepts %s', (v) => {
    expect(isSafeExtensionVersion(v)).toBe(true)
  })

  test.each([
    '',
    'dev',
    '1.0',
    '01.0.0',
    '1.0.0+build',
    'v1.0.0',
    '1.0.0/..',
    '../1.0.0',
    `1.0.0-${'a'.repeat(80)}`
  ])('rejects %j', (v) => {
    expect(isSafeExtensionVersion(v)).toBe(false)
  })
})

describe('isSafeBundleEntryName', () => {
  test.each(['extension.toml', 'assets/app.js', 'a/b/c.png', 'Icon-2.svg'])('accepts %s', (n) => {
    expect(isSafeBundleEntryName(n)).toBe(true)
  })

  test.each([
    '',
    '/etc/passwd',
    '../x.html',
    'a/../b',
    'a\\b',
    './x',
    'a//b',
    'sp ace.html',
    'a/b/',
    `${'x'.repeat(201)}.html`
  ])('rejects %j', (n) => {
    expect(isSafeBundleEntryName(n)).toBe(false)
  })
})

describe('layout', () => {
  test('root and bundle dir follow ~/.solus/extensions/<id>/<version>', () => {
    expect(extensionsRoot('/home/t')).toBe('/home/t/.solus/extensions')
    expect(bundleDir('/home/t/.solus/extensions', 'bom', '1.2.0')).toBe(
      '/home/t/.solus/extensions/bom/1.2.0'
    )
  })
})

describe('isAtOrUnder', () => {
  test('parent, child, and outsider', () => {
    expect(isAtOrUnder('/r', '/r')).toBe(true)
    expect(isAtOrUnder('/r', '/r/a/b')).toBe(true)
    expect(isAtOrUnder('/r', '/rx')).toBe(false)
    expect(isAtOrUnder('/r', '/')).toBe(false)
    expect(isAtOrUnder('/r', '/r/../s')).toBe(false)
  })
})

describe('resolveInsideRoot', () => {
  const realpath = (p: string): string | null => {
    if (p === '/root/link.html') return '/etc/passwd' // symlink escape
    if (p === '/root/ok.html' || p === '/root' || p === '/root/sub/x.css') return p
    return null
  }

  test('resolves a plain file under the root to its canonical path', () => {
    expect(resolveInsideRoot('/root', 'ok.html', realpath)).toBe('/root/ok.html')
    expect(resolveInsideRoot('/root', 'sub/x.css', realpath)).toBe('/root/sub/x.css')
  })

  test('refuses a symlink whose target escapes the root', () => {
    expect(resolveInsideRoot('/root', 'link.html', realpath)).toBeNull()
  })

  test('refuses a missing file, or a root that itself does not resolve', () => {
    expect(resolveInsideRoot('/root', 'nope.html', realpath)).toBeNull()
    expect(resolveInsideRoot('/gone', 'ok.html', realpath)).toBeNull()
  })

  test('the canonical root is what the containment check uses', () => {
    const viaLink = (p: string): string | null =>
      p.startsWith('/alias') ? p.replace('/alias', '/real') : p
    expect(resolveInsideRoot('/alias', 'a.html', viaLink)).toBe('/real/a.html')
  })
})
