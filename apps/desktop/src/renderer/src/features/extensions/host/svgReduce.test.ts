// SOLUSDEV-235 / EXT-12 — parity with solus_api.extensions.svg (test_extension_svg.py).
import { describe, it, expect } from 'vitest'
import { MANIFEST_LIMITS } from '@solus/shared-types'
import { reduceSvg } from './svgReduce'

const svg = (body: string, rootAttrs = ''): string =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"${rootAttrs}>${body}</svg>`

const VALID_ICON =
  '<?xml version="1.0"?>' +
  svg(
    '<title>BOM</title><g fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round">' +
      '<path d="M4 4h16v16H4z"/><circle cx="12" cy="12" r="3" fill="#ffb000"/></g>'
  )

describe('reduceSvg', () => {
  it('reduces a valid icon: colours → currentColor, none survives, title kept, declaration dropped', () => {
    const out = reduceSvg(VALID_ICON)
    expect(out).not.toBeNull()
    expect(out!.startsWith('<svg xmlns="http://www.w3.org/2000/svg"')).toBe(true)
    expect(out).toContain('stroke="currentColor"')
    expect(out).toContain('fill="currentColor"')
    expect(out).toContain('fill="none"')
    expect(out).not.toContain('#fff')
    expect(out).not.toContain('#ffb000')
    expect(out).toContain('<title>BOM</title>')
    expect(out).toContain('<path d="M4 4h16v16H4z"/>')
    expect(out).not.toContain('<?xml')
  })

  it('is idempotent', () => {
    const once = reduceSvg(VALID_ICON)!
    expect(reduceSvg(once)).toBe(once)
  })

  it('serializes like the Python reducer (self-closing empties, xmlns first, escaped values)', () => {
    expect(reduceSvg(svg('<path d="M0 0"/>'))).toBe(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0"/></svg>'
    )
    expect(reduceSvg(svg('<title>a &lt; b &amp; "c"</title>'))).toBe(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><title>a &lt; b &amp; "c"</title></svg>'
    )
  })

  it('rejects an oversized icon before parsing', () => {
    const big = svg('<path d="M0 0h1"/>'.repeat(2000))
    expect(reduceSvg(big, 1024)).toBeNull()
    expect(reduceSvg(svg('<path d="M0 0"/>'), MANIFEST_LIMITS.iconBytes)).not.toBeNull()
  })

  it.each([
    '<!DOCTYPE svg [<!ENTITY x "y">]>' + svg('&x;'),
    '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://x/svg11.dtd">' + svg(''),
    '<!ENTITY x "y">' + svg(''),
    '<!doctype svg>' + svg('')
  ])('rejects DOCTYPE / ENTITY on sight: %s', (text) => {
    expect(reduceSvg(text)).toBeNull()
  })

  it('rejects processing instructions other than the XML declaration', () => {
    expect(
      reduceSvg('<?xml version="1.0"?><?xml-stylesheet href="evil.css"?>' + svg(''))
    ).toBeNull()
    expect(reduceSvg('<?xml version="1.0"?>' + svg('<path d="M0 0"/>'))).not.toBeNull()
  })

  it.each([
    ['script', '<script>alert(1)</script>'],
    ['foreignObject', '<foreignObject><div>x</div></foreignObject>'],
    ['image', '<image href="https://evil/x.png"/>'],
    ['use', '<use href="#a"/>'],
    ['a', '<a href="https://evil"><path d="M0 0"/></a>'],
    ['style', '<style>path{fill:red}</style>'],
    ['text', '<text>hi</text>'],
    ['defs', '<defs/>'],
    ['prefixed path', '<svg:path d="M0 0"/>'],
    ['animate', '<animate attributeName="x"/>']
  ])('rejects a disallowed element: %s', (_label, body) => {
    expect(reduceSvg(svg(body))).toBeNull()
  })

  it.each([
    ['onload', '<path d="M0 0" onload="alert(1)"/>'],
    ['onclick (mixed case)', '<path d="M0 0" OnClick="x"/>'],
    ['href', '<path d="M0 0" href="x"/>'],
    ['xlink:href', '<path d="M0 0" xlink:href="x"/>'],
    ['style', '<path d="M0 0" style="fill:red"/>'],
    ['class', '<path d="M0 0" class="c"/>'],
    ['id', '<path d="M0 0" id="i"/>'],
    ['filter', '<path d="M0 0" filter="url(#f)"/>'],
    ['data-*', '<path d="M0 0" data-x="1"/>']
  ])('rejects a disallowed attribute: %s', (_label, body) => {
    expect(reduceSvg(svg(body))).toBeNull()
  })

  it.each(['url(#grad)', 'url(https://evil/x)', 'rgb(1,2,3)', 'hsl(1,2%,3%)', '#ggg', 'red;x', ''])(
    'rejects a non-plain colour: %s',
    (colour) => {
      expect(reduceSvg(svg(`<path d="M0 0" fill="${colour}"/>`))).toBeNull()
    }
  )

  it.each(['red', 'CurrentColor', 'currentColor', '#abc', '#abcd', '#aabbcc', '#aabbccdd'])(
    'rewrites the plain colour %s to currentColor',
    (colour) => {
      const out = reduceSvg(svg(`<path d="M0 0" stroke="${colour}"/>`))
      expect(out).toContain('stroke="currentColor"')
      expect(out).not.toContain(colour === 'currentColor' ? 'zzz' : colour)
    }
  )

  it('rejects a foreign xmlns, a non-svg root, and malformed XML', () => {
    expect(reduceSvg('<svg xmlns="http://www.w3.org/1999/xhtml"><path d="M0 0"/></svg>')).toBeNull()
    expect(reduceSvg('<g xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></g>')).toBeNull()
    expect(reduceSvg('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"></svg>')).toBeNull()
    expect(reduceSvg('')).toBeNull()
    expect(reduceSvg('not svg at all')).toBeNull()
  })

  it('accepts a root without xmlns and adds it; drops comments and stray text', () => {
    expect(reduceSvg('<svg viewBox="0 0 1 1"><!-- c --> stray <path d="M0 0"/></svg>')).toBe(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><path d="M0 0"/></svg>'
    )
  })
})
