import { describe, expect, it } from 'vitest'
import { analyse, isCircle, regionFor, type Point } from './circleDetector'

function circle(cx: number, cy: number, r: number, n = 36, sweep = 2 * Math.PI): Point[] {
  return Array.from({ length: n + 1 }, (_, i) => {
    const a = (i / n) * sweep
    return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) }
  })
}

const display = { id: 1, bounds: { x: 0, y: 0, width: 1920, height: 1080 }, scaleFactor: 1 }

describe('circleDetector (docs/architecture/sol-window.md §4)', () => {
  it('a synthetic 36-point circle passes', () => {
    const a = analyse(circle(500, 400, 100))
    expect(a.sweepDeg).toBeGreaterThan(350)
    expect(a.closeRatio).toBeLessThan(0.05)
    expect(a.travelPx).toBeGreaterThan(600)
    expect(isCircle(a)).toBe(true)
  })

  it('a straight line fails', () => {
    const line = Array.from({ length: 40 }, (_, i) => ({ x: 100 + i * 10, y: 300 }))
    expect(isCircle(analyse(line))).toBe(false)
  })

  it('a half circle fails on sweep', () => {
    const a = analyse(circle(500, 400, 150, 36, Math.PI))
    expect(a.sweepDeg).toBeLessThan(300)
    expect(isCircle(a)).toBe(false)
  })

  it('a loop with a small gap passes', () => {
    // 320° of a 100 px circle: the ends are ~68 px apart on a 200 px diagonal → ratio < 0.25
    const a = analyse(circle(500, 400, 100, 36, (320 / 180) * Math.PI))
    expect(a.closeRatio).toBeLessThan(0.25)
    expect(isCircle(a)).toBe(true)
  })

  it('a tiny loop (< 40 px) fails', () => {
    expect(isCircle(analyse(circle(500, 400, 15)))).toBe(false)
  })

  it('an empty or single-point path never passes', () => {
    expect(isCircle(analyse([]))).toBe(false)
    expect(isCircle(analyse([{ x: 1, y: 1 }]))).toBe(false)
  })

  it('regionFor adds the 12 % margin', () => {
    const a = analyse(circle(500, 400, 100))
    const r = regionFor(a, display)
    expect(r.x).toBeCloseTo(400 - 24, 0)
    expect(r.y).toBeCloseTo(300 - 24, 0)
    expect(r.width).toBeCloseTo(248, 0)
    expect(r.height).toBeCloseTo(248, 0)
  })

  it('regionFor clamps to the display bounds', () => {
    const a = analyse(circle(1900, 20, 100))
    const r = regionFor(a, display)
    expect(r.x).toBeGreaterThanOrEqual(0)
    expect(r.y).toBe(0)
    expect(r.x + r.width).toBeLessThanOrEqual(1920)
    expect(r.width).toBeGreaterThan(0)
    expect(r.height).toBeGreaterThan(0)
  })
})

it('an approach segment before the loop does not count as an open end', () => {
  const path: { x: number; y: number }[] = []
  for (let i = 0; i <= 10; i++) path.push({ x: 100 + i * 20, y: 300 }) // walking in from the left
  for (let i = 0; i <= 40; i++) {
    const a = (2 * Math.PI * i) / 40
    path.push({ x: Math.round(300 + 120 * Math.cos(a)), y: Math.round(300 + 120 * Math.sin(a)) })
  }
  const a = analyse(path)
  expect(a.closeRatio).toBeLessThan(0.25)
  expect(isCircle(a)).toBe(true)
})
