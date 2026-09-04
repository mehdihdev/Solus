// SOLUSDEV-235 / EXT-13 — extEntryUrl applies main's protocol rules before a URL exists.
import { describe, it, expect } from 'vitest'
import { extEntryUrl, isSafeExtVersion, EXT_SERVED_SUFFIXES } from './extUrl'

describe('extEntryUrl', () => {
  it('spells solus-ext://<id>/<version>/<entry>', () => {
    expect(extEntryUrl('bom', '1.2.0', 'page.html')).toBe('solus-ext://bom/1.2.0/page.html')
    expect(extEntryUrl('bom', '1.2.0-beta.1', 'ui/page.html')).toBe(
      'solus-ext://bom/1.2.0-beta.1/ui/page.html'
    )
  })

  it('serves developer registrations under the literal dev version, with a reload nonce', () => {
    expect(extEntryUrl('bom', 'dev', 'page.html')).toBe('solus-ext://bom/dev/page.html')
    expect(extEntryUrl('bom', 'dev', 'page.html', { nonce: 3 })).toBe(
      'solus-ext://bom/dev/page.html?r=3'
    )
    expect(extEntryUrl('bom', 'dev', 'page.html', { nonce: -2.7 })).toBe(
      'solus-ext://bom/dev/page.html?r=0'
    )
  })

  it.each([
    ['Bom', '1.0.0', 'page.html'],
    ['b', '1.0.0', 'page.html'],
    ['2bom', '1.0.0', 'page.html'],
    ['__proto__', '1.0.0', 'page.html'],
    ['constructor', '1.0.0', 'page.html'],
    ['a'.repeat(65), '1.0.0', 'page.html']
  ])('refuses the unsafe id %s', (id, version, entry) => {
    expect(extEntryUrl(id, version, entry)).toBeNull()
  })

  it.each(['1.0', 'v1.0.0', '01.0.0', 'latest', '', '..', `1.0.0-${'a'.repeat(70)}`])(
    'refuses the version %s',
    (version) => {
      expect(isSafeExtVersion(version)).toBe(false)
      expect(extEntryUrl('bom', version, 'page.html')).toBeNull()
    }
  )

  it.each([
    '/page.html',
    '../page.html',
    'a/../page.html',
    './page.html',
    'a//page.html',
    'a\\page.html',
    'page.exe',
    'page.html.bak',
    'page',
    '',
    `${'a'.repeat(200)}.html`,
    'sp ace.html',
    'q?.html'
  ])('refuses the entry %j', (entry) => {
    expect(extEntryUrl('bom', '1.0.0', entry)).toBeNull()
  })

  it('accepts every served suffix and nothing case-sensitive about it', () => {
    for (const suffix of EXT_SERVED_SUFFIXES) {
      expect(extEntryUrl('bom', '1.0.0', `asset${suffix}`)).toBe(
        `solus-ext://bom/1.0.0/asset${suffix}`
      )
    }
    expect(extEntryUrl('bom', '1.0.0', 'PAGE.HTML')).toBe('solus-ext://bom/1.0.0/PAGE.HTML')
  })
})
