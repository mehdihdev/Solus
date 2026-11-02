// SOLUSDEV-319 Phase 4 H-1: ma/integ are amortised O(1) per sample (a running window sum),
// and agree with the per-sample oldest->newest recomputation they replaced
// (docs/api/bench-view.md §4.5).
import { describe, expect, it } from 'vitest'
import { MAX_FILTER_SAMPLES, evaluateExpression, parseExpression, type Sample } from './expression'
import { Fifo } from './expressionWindow'

const REF = { deviceId: 'd', signal: 'a' }
const REL_TOL = 1e-9

// 11 windowed filters over one 10 s window: the most a 64-node expression holds.
const WORST_FILTERS = Array.from(
  { length: 11 },
  (_, i) => `${i % 2 ? 'ma' : 'integ'}(sig("d","a"), 10)`
).join(' + ')
// Twice the sample cap, so the second half runs on a full window evicting every sample.
const WORST_SAMPLES: Sample[] = Array.from({ length: 2 * MAX_FILTER_SAMPLES }, (_, i) => ({
  t: i * 0.001,
  value: Math.sin(i) * 100
}))

function seededRandom(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0
    return state / 2 ** 32
  }
}

const sum = (values: readonly number[]): number => values.reduce((a, b) => a + b, 0)

interface Expected {
  value: number
  scale: number
}

function naiveReduce(name: 'ma' | 'integ', kept: readonly Sample[]): Expected {
  if (name === 'ma') {
    const terms = kept.map((s) => s.value)
    const n = Math.max(kept.length, 1)
    return {
      value: kept.length ? sum(terms) / kept.length : Number.NaN,
      scale: sum(terms.map(Math.abs)) / n
    }
  }
  const terms = kept
    .slice(1)
    .map((cur, i) => ((cur.t - kept[i].t) * (cur.value + kept[i].value)) / 2)
  return { value: sum(terms), scale: sum(terms.map(Math.abs)) }
}

/** The pre-H-1 algorithm; scale (sum of |terms|) bounds its rounding error. */
function naiveFilter(name: 'ma' | 'integ', window: number, series: readonly Sample[]): Expected[] {
  let kept: Sample[] = []
  let last: number | null = null
  return series.map(({ t, value }) => {
    if (last !== null && t - last > window) kept = []
    last = t
    if (Number.isFinite(value)) kept.push({ t, value })
    kept = kept.filter((s) => s.t > t - window).slice(-MAX_FILTER_SAMPLES)
    const out = naiveReduce(name, kept)
    return { value: Number.isFinite(out.value) ? out.value : Number.NaN, scale: out.scale }
  })
}

function close(actual: number, expected: Expected): boolean {
  if (Number.isNaN(actual) || Number.isNaN(expected.value)) {
    return Number.isNaN(actual) && Number.isNaN(expected.value)
  }
  const bound =
    REL_TOL * Math.max(Math.abs(actual), Math.abs(expected.value)) + 1e-12 * expected.scale
  return Math.abs(actual - expected.value) <= bound
}

function randomSeries(rand: () => number, window: number): Sample[] {
  const steps = [0.001, 0.003, 0.01]
  const count = 500 + Math.floor(rand() * 2500)
  let t = 0
  return Array.from({ length: count }, () => {
    t += rand() > 0.002 ? steps[Math.floor(rand() * steps.length)] : window + 0.5
    const roll = rand()
    const x = roll < 0.05 ? Number.NaN : rand() * 2000 - 1000
    return { t, value: roll >= 0.05 && roll < 0.07 ? x * 1e9 : x }
  })
}

const run = (expression: string, samples: readonly Sample[]): number[] =>
  evaluateExpression(parseExpression(expression), [{ ref: REF, samples }]).map((s) => s.value)

describe('windowed filter cost', () => {
  it('evaluates 11 filters over full windows well inside the budget', () => {
    const parsed = parseExpression(WORST_FILTERS)
    expect(parsed.filterCount).toBe(11)
    const start = performance.now()
    const out = evaluateExpression(parsed, [{ ref: REF, samples: WORST_SAMPLES }])
    const elapsed = performance.now() - start
    expect(out).toHaveLength(WORST_SAMPLES.length)
    expect(elapsed).toBeLessThan(200)
  })

  it('keeps 32 worst-case derived signals bounded', () => {
    const parsed = parseExpression(WORST_FILTERS)
    const start = performance.now()
    for (let i = 0; i < 32; i++) evaluateExpression(parsed, [{ ref: REF, samples: WORST_SAMPLES }])
    expect(performance.now() - start).toBeLessThan(3000)
  })
})

describe.each(['ma', 'integ'] as const)('%s running window', (name) => {
  it('matches the per-sample recomputation (seeded fuzz)', () => {
    const rand = seededRandom(1_190_319)
    const windows = [0.05, 0.5, 2, 10]
    for (let trial = 0; trial < 12; trial++) {
      const window = windows[Math.floor(rand() * windows.length)]
      const series = randomSeries(rand, window)
      const got = run(`${name}(sig("d","a"), ${window})`, series)
      const expected = naiveFilter(name, window, series)
      const bad = got.findIndex((v, i) => !close(v, expected[i]))
      expect(bad, `trial ${trial} index ${bad}: ${got[bad]} vs ${expected[bad]?.value}`).toBe(-1)
    }
  })

  it('clears an overflow once the huge samples leave the window', () => {
    const series = [
      { t: 0, value: 1e308 },
      { t: 0.25, value: 1e308 },
      { t: 0.5, value: 1 },
      { t: 0.75, value: 1 },
      { t: 1.3, value: 1 },
      { t: 1.4, value: 3 }
    ]
    const out = run(`${name}(sig("d","a"), 1)`, series)
    expect(Number.isNaN(out[1]) && Number.isNaN(out[2])).toBe(true)
    const expected = naiveFilter(name, 1, series)
    for (let i = 4; i < series.length; i++) {
      expect(out[i]).toBeCloseTo(expected[i].value, 12)
    }
  })
})

describe('precision and storage', () => {
  it('keeps small values once a large value leaves the window', () => {
    const series = [
      { t: 0, value: 1e17 },
      { t: 0.5, value: 1e-3 },
      { t: 0.9, value: 3e-3 },
      { t: 1.2, value: 5e-3 }
    ]
    const out = run('ma(sig("d","a"), 1)', series)
    expect(Math.abs(out[3] - 3e-3)).toBeLessThan(3e-3 * 1e-12)
  })

  it('Fifo keeps order across compaction', () => {
    const fifo = new Fifo<number>()
    for (let i = 0; i < 5000; i++) {
      fifo.push(i)
      if (i % 3 !== 0) fifo.shift()
    }
    expect(fifo.length).toBe(1667)
    expect(fifo.first()).toBe(3333)
    expect(fifo.last()).toBe(4999)
    expect([...fifo]).toEqual(Array.from({ length: 1667 }, (_, i) => 3333 + i))
    fifo.clear()
    expect(fifo.length).toBe(0)
  })
})
