import { CARD_HEIGHT, CARD_WIDTH } from './layout'

/** Camera-only fit for small overviews; world coordinates and saved layouts stay untouched. */
export function frameSmallOverview(
  viewport: HTMLElement,
  stage: HTMLElement,
  maxCards = 6
): boolean {
  if (stage.dataset.viewZoom === 'actual') return false
  const cards = Array.from(stage.querySelectorAll<HTMLElement>(':scope > .graph-node'))
  const rail = parseFloat(getComputedStyle(viewport).paddingRight) || 0
  const width = viewport.clientWidth - rail
  const height = viewport.clientHeight
  if (cards.length < 2 || cards.length > maxCards || width <= 0 || height <= 0) return false
  const xs = cards.map((card) => parseFloat(card.style.left))
  const ys = cards.map((card) => parseFloat(card.style.top))
  if ([...xs, ...ys].some((value) => !Number.isFinite(value))) return false
  const left = Math.min(...xs),
    right = Math.max(...xs) + CARD_WIDTH
  const top = Math.min(...ys),
    bottom = Math.max(...ys) + CARD_HEIGHT
  const scale = Math.min(
    1,
    Math.max(1, width - 48) / (right - left + 48),
    Math.max(1, height - 80) / (bottom - top + 48)
  )
  stage.style.setProperty('zoom', String(scale))
  stage.style.margin = '0'
  viewport.scrollLeft = Math.max(0, ((left + right) * scale) / 2 - width / 2)
  viewport.scrollTop = Math.max(0, ((top + bottom) * scale) / 2 - height / 2)
  return true
}

/** Explicit user zoom choice; changing the camera never persists graph coordinates. */
export function setGraphZoom(viewport: HTMLElement, fit: boolean): void {
  const stage = viewport.firstElementChild
  if (!(stage instanceof HTMLElement)) return
  if (fit) {
    stage.dataset.viewZoom = 'fit'
    frameSmallOverview(viewport, stage, 24)
    return
  }
  const old = Number(stage.style.getPropertyValue('zoom')) || 1
  const rail = parseFloat(getComputedStyle(viewport).paddingRight) || 0
  const width = viewport.clientWidth - rail
  const height = viewport.clientHeight
  const center = {
    x: (viewport.scrollLeft + width / 2) / old,
    y: (viewport.scrollTop + height / 2) / old
  }
  stage.dataset.viewZoom = 'actual'
  stage.style.setProperty('zoom', '1')
  stage.style.margin = '0'
  viewport.scrollLeft = Math.max(0, center.x - width / 2)
  viewport.scrollTop = Math.max(0, center.y - height / 2)
}
