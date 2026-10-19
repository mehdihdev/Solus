// App-wide scrollbars (SOLUSDEV-317): thin, rounded, token-coloured so all
// five themes re-skin them, with no bright system track. Pinned by reading the
// global stylesheet — jsdom renders no scrollbars to inspect.
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const css = fs.readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), 'main.css'),
  'utf8'
)

/** The declaration block of the first rule whose selector list contains `selector`. */
function block(selector: string): string {
  const at = css.indexOf(selector)
  expect(at, `${selector} is styled`).toBeGreaterThan(-1)
  return css.slice(css.indexOf('{', at) + 1, css.indexOf('}', at))
}

describe('themed scrollbars', () => {
  it('are thin everywhere, both directions', () => {
    const bar = block('::-webkit-scrollbar {')
    expect(bar).toMatch(/width:\s*10px/)
    expect(bar).toMatch(/height:\s*10px/)
  })

  it('have no visible track or corner', () => {
    expect(block('::-webkit-scrollbar-track')).toMatch(/background:\s*transparent/)
    expect(block('::-webkit-scrollbar-corner')).toMatch(/background:\s*transparent/)
  })

  it('draw a rounded thumb in theme tokens, inset from the edge, brighter on hover', () => {
    const thumb = block('::-webkit-scrollbar-thumb {')
    expect(thumb).toMatch(/background-color:\s*var\(--bd\)/)
    expect(thumb).toMatch(/border-radius/)
    expect(thumb).toMatch(/background-clip:\s*padding-box/)
    expect(block('::-webkit-scrollbar-thumb:hover')).toMatch(/var\(--mut\)/)
  })

  it('never set scrollbar-color, which makes Chromium ignore the styling above', () => {
    expect(css).not.toMatch(/scrollbar-color\s*:/)
  })
})
