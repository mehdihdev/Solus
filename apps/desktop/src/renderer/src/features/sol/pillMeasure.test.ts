// SOLUSDEV-319: what the pill reports to main. While the panel animates open
// toward its content, main is told the TARGET height (grow the window first,
// then the content animates into it); while it shrinks, the current height.
import { describe, it, expect } from 'vitest'
import { measurePill } from './pillMeasure'

function pillWith(total: number, panel?: number, body?: number): HTMLElement {
  const pill = document.createElement('div')
  pill.getBoundingClientRect = () => ({ height: total }) as DOMRect
  if (panel !== undefined) {
    const p = document.createElement('section')
    p.className = 'sol-pill-panel'
    p.getBoundingClientRect = () => ({ height: panel }) as DOMRect
    const b = document.createElement('div')
    b.className = 'sol-pill-panel-body'
    b.getBoundingClientRect = () => ({ height: body ?? panel }) as DOMRect
    p.appendChild(b)
    pill.appendChild(p)
  }
  return pill
}

describe('measurePill', () => {
  it('without a panel reports the pill itself, rounded up', () => {
    expect(measurePill(pillWith(233.4))).toEqual({ report: 234, chrome: 233.4 })
  })

  it('a panel growing toward its content reports the target height', () => {
    expect(measurePill(pillWith(300, 100, 250))).toEqual({ report: 450, chrome: 200 })
  })

  it('a panel shrinking reports where it is now', () => {
    expect(measurePill(pillWith(300, 100, 40))).toEqual({ report: 300, chrome: 200 })
  })
})
