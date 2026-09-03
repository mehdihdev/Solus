// SOLUSDEV-235 / EXT-05 — the solus-ext:// scheme: URL discipline, realpath
// containment, content types, CSP on html, 404 for everything else, never throws.
import { describe, expect, test } from 'vitest'
import { upsertInstalled } from './extensionIndex'
import {
  createExtProtocolHandler,
  EXT_HTML_CSP,
  EXT_SCHEME_PRIVILEGES,
  parseExtUrl,
  serveExtAsset,
  toResponse
} from './extProtocol'
import { fakeExtensionFs, seedDir, seedFile, type FakeExtensionFs } from './testing/fakeExtensionFs'

const ROOT = '/home/tester/.solus/extensions'
const HASH = 'a'.repeat(64)

function installedFs(): FakeExtensionFs {
  const fs = fakeExtensionFs()
  upsertInstalled(
    'bom',
    { version: '1.2.0', contentHash: HASH, installedAt: 'x', source: 'registry' },
    fs
  )
  seedFile(fs, `${ROOT}/bom/1.2.0/widget.html`, '<p>hi</p>')
  seedFile(fs, `${ROOT}/bom/1.2.0/assets/app.js`, 'x()')
  seedFile(fs, `${ROOT}/bom/1.2.0/Icon.SVG`, '<svg/>')
  seedFile(fs, `${ROOT}/bom/1.2.0/notes.txt`, 'no')
  seedDir(fs, `${ROOT}/bom/1.2.0/assets`)
  return fs
}

describe('parseExtUrl', () => {
  test('parses id / version / path', () => {
    expect(parseExtUrl('solus-ext://bom/1.2.0/widget.html')).toEqual({
      id: 'bom',
      version: '1.2.0',
      path: 'widget.html'
    })
    expect(parseExtUrl('solus-ext://bom/1.2.0/assets/app.js?x=1#y')).toEqual({
      id: 'bom',
      version: '1.2.0',
      path: 'assets/app.js'
    })
  })

  test('accepts the literal dev version segment', () => {
    expect(parseExtUrl('solus-ext://bom/dev/widget.html')?.version).toBe('dev')
  })

  test.each([
    ['another scheme', 'https://bom/1.2.0/widget.html'],
    ['no path', 'solus-ext://bom/1.2.0'],
    ['empty path', 'solus-ext://bom/1.2.0/'],
    ['unsafe id', 'solus-ext://Bom_x/1.2.0/widget.html'],
    ['reserved id', 'solus-ext://constructor/1.2.0/widget.html'],
    ['non-semver version', 'solus-ext://bom/latest/widget.html'],
    ['traversal', 'solus-ext://bom/1.2.0/../../projects.json'],
    ['encoded traversal', 'solus-ext://bom/1.2.0/%2e%2e/%2e%2e/index.json'],
    ['encoded slash smuggling', 'solus-ext://bom/1.2.0/a%2f..%2fb.html'],
    ['backslash', 'solus-ext://bom/1.2.0/a%5cb.html'],
    ['disallowed suffix', 'solus-ext://bom/1.2.0/notes.txt'],
    ['no suffix', 'solus-ext://bom/1.2.0/README'],
    ['userinfo', 'solus-ext://u:p@bom/1.2.0/widget.html'],
    ['a port', 'solus-ext://bom:8080/1.2.0/widget.html'],
    ['not a URL', 'nope']
  ])('rejects %s', (_why, url) => {
    expect(parseExtUrl(url)).toBeNull()
  })
})

describe('serveExtAsset', () => {
  test('serves an installed asset with its content type, nosniff, and CSP on html', () => {
    const fs = installedFs()
    const html = serveExtAsset('solus-ext://bom/1.2.0/widget.html', fs)
    expect(html.status).toBe(200)
    expect(new TextDecoder().decode(html.body as Uint8Array)).toBe('<p>hi</p>')
    expect(html.headers['content-type']).toBe('text/html; charset=utf-8')
    expect(html.headers['content-security-policy']).toBe(EXT_HTML_CSP)
    expect(html.headers['x-content-type-options']).toBe('nosniff')

    const js = serveExtAsset('solus-ext://bom/1.2.0/assets/app.js', fs)
    expect(js.status).toBe(200)
    expect(js.headers['content-type']).toBe('text/javascript; charset=utf-8')
    expect(js.headers['content-security-policy']).toBeUndefined()
  })

  test('content type is decided by the lower-cased suffix', () => {
    const res = serveExtAsset('solus-ext://bom/1.2.0/Icon.SVG', installedFs())
    expect(res.status).toBe(200)
    expect(res.headers['content-type']).toBe('image/svg+xml')
  })

  test.each([
    ['an unknown id', 'solus-ext://cad/1.2.0/widget.html'],
    ['a version that is not the installed one', 'solus-ext://bom/1.3.0/widget.html'],
    ['dev for a registry install', 'solus-ext://bom/dev/widget.html'],
    ['a missing file', 'solus-ext://bom/1.2.0/gone.html'],
    ['a directory', 'solus-ext://bom/1.2.0/assets.json'],
    ['a disallowed suffix even when the file exists', 'solus-ext://bom/1.2.0/notes.txt'],
    ['an unparseable URL', 'solus-ext://bom/../x.html']
  ])('404 for %s', (_why, url) => {
    const fs = installedFs()
    seedDir(fs, `${ROOT}/bom/1.2.0/assets.json`)
    const res = serveExtAsset(url, fs)
    expect(res.status).toBe(404)
    expect(res.body).toBeNull()
    expect(res.headers['x-content-type-options']).toBe('nosniff')
  })

  test('404 for a symlink whose target escapes the bundle', () => {
    const fs = installedFs()
    seedFile(fs, '/home/tester/.solus/projects.json', '{}')
    fs.links.set(`${ROOT}/bom/1.2.0/leak.json`, '/home/tester/.solus/projects.json')
    expect(serveExtAsset('solus-ext://bom/1.2.0/leak.json', fs).status).toBe(404)
  })

  test('serves a symlink that stays inside the bundle', () => {
    const fs = installedFs()
    fs.links.set(`${ROOT}/bom/1.2.0/alias.js`, `${ROOT}/bom/1.2.0/assets/app.js`)
    expect(serveExtAsset('solus-ext://bom/1.2.0/alias.js', fs).status).toBe(200)
  })
})

describe('serveExtAsset — dev registrations and failures', () => {
  test('serves a dev registration from its devPath under the dev version', () => {
    const fs = fakeExtensionFs()
    seedFile(fs, '/ws/my-ext/widget.html', '<p>dev</p>')
    upsertInstalled(
      'my-ext',
      {
        version: '0.1.0',
        contentHash: HASH,
        installedAt: 'x',
        source: 'dev',
        devPath: '/ws/my-ext'
      },
      fs
    )
    expect(serveExtAsset('solus-ext://my-ext/dev/widget.html', fs).status).toBe(200)
    // The semver of a dev entry is NOT served — dev bundles are addressed as `dev`.
    expect(serveExtAsset('solus-ext://my-ext/0.1.0/widget.html', fs).status).toBe(404)
  })

  test('a dev registration whose devPath became unsafe is not served', () => {
    const fs = fakeExtensionFs()
    seedFile(fs, '/home/tester/secret.html', 'x')
    upsertInstalled(
      'my-ext',
      {
        version: '0.1.0',
        contentHash: HASH,
        installedAt: 'x',
        source: 'dev',
        devPath: '/home/tester'
      },
      fs
    )
    expect(serveExtAsset('solus-ext://my-ext/dev/secret.html', fs).status).toBe(404)
  })

  test('never throws — a filesystem failure is a 404', () => {
    const fs = installedFs()
    fs.readFile = () => {
      throw new Error('EIO')
    }
    expect(serveExtAsset('solus-ext://bom/1.2.0/widget.html', fs).status).toBe(404)
  })
})

describe('protocol handler', () => {
  test('privileges match ADR-035 (standard, secure, no fetch, no CORS)', () => {
    expect(EXT_SCHEME_PRIVILEGES).toEqual({
      standard: true,
      secure: true,
      supportFetchAPI: false,
      corsEnabled: false
    })
  })

  test('builds a fetch Response for hits and misses', async () => {
    const handler = createExtProtocolHandler(installedFs())
    const hit = handler({ url: 'solus-ext://bom/1.2.0/widget.html' })
    expect(hit.status).toBe(200)
    expect(hit.headers.get('content-security-policy')).toBe(EXT_HTML_CSP)
    expect(await hit.text()).toBe('<p>hi</p>')
    const miss = handler({ url: 'solus-ext://bom/1.2.0/gone.html' })
    expect(miss.status).toBe(404)
    expect(toResponse({ status: 404, headers: {}, body: null }).body).toBeNull()
  })
})
