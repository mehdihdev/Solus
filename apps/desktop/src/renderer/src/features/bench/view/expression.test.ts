// SOLUSDEV-319 B2: the renderer's derived-signal evaluator runs the SAME shared vectors
// as the server (docs/api/bench-view.md §4; architecture/bench-view.md §2).
import { describe, expect, it } from 'vitest'
import vectorsText from '../../../../../../../../packages/shared-types/fixtures/bench-expression-vectors.json?raw'
import expressionSource from './expression.ts?raw'
import {
  ERROR_MESSAGES,
  ExpressionError,
  IncrementalEvaluator,
  MAX_EXPRESSION_CHARS,
  evaluateExpression,
  parseExpression,
  tryParseExpression,
  type Sample,
  type SignalRef,
  type SeriesInput
} from './expression'

type VectorNumber = number | 'NaN' | 'Infinity' | '-Infinity'
type VectorPair = [VectorNumber, VectorNumber]
interface ParseVector {
  name: string
  expression: string
  accept?: { node_count: number; depth: number; refs: { device_id: string; signal: string }[] }
  reject?: { code: string; position: number; length: number }
}
interface EvalInput {
  device_id: string
  signal: string
  samples?: VectorPair[]
  ramp?: { count: number; dt: number; dv: number }
}
interface EvalVector {
  name: string
  expression: string
  inputs: EvalInput[]
  timestamps?: VectorNumber[]
  at?: number
  expected?: VectorPair[]
  expected_count?: number
  expected_head?: VectorPair[]
  expected_tail?: VectorPair[]
}
const vectors = JSON.parse(vectorsText) as { parse: ParseVector[]; evaluate: EvalVector[] }

function decodeVectorNumber(value: VectorNumber): number {
  if (value === 'NaN') return Number.NaN
  if (value === 'Infinity') return Number.POSITIVE_INFINITY
  if (value === '-Infinity') return Number.NEGATIVE_INFINITY
  return value
}

function vectorInputs(vector: EvalVector): SeriesInput[] {
  return vector.inputs.map((input) => {
    const ref = { deviceId: input.device_id, signal: input.signal }
    if (input.ramp) {
      const { count, dt, dv } = input.ramp
      return {
        ref,
        samples: Array.from({ length: count }, (_, i) => ({ t: i * dt, value: i * dv }))
      }
    }
    const samples = (input.samples ?? []).map(([t, v]) => ({
      t: decodeVectorNumber(t),
      value: decodeVectorNumber(v)
    }))
    return { ref, samples }
  })
}

function timeBase(vector: EvalVector): number[] | undefined {
  return vector.timestamps?.map(decodeVectorNumber)
}

function withinTolerance(actual: number, expected: number): boolean {
  if (Number.isNaN(actual) || Number.isNaN(expected)) {
    return Number.isNaN(actual) && Number.isNaN(expected)
  }
  return (
    actual === expected ||
    Math.abs(actual - expected) <= 1e-9 * Math.max(Math.abs(actual), Math.abs(expected))
  )
}

function expectSeries(actual: Sample[], expected: VectorPair[]): void {
  expect(actual.length).toBe(expected.length)
  actual.forEach((sample, i) => {
    const [t, v] = expected[i]
    expect(withinTolerance(sample.t, decodeVectorNumber(t)), `t ${sample.t} vs ${t}`).toBe(true)
    expect(
      withinTolerance(sample.value, decodeVectorNumber(v)),
      `v@${sample.t} ${sample.value} vs ${v}`
    ).toBe(true)
  })
}

function checkVector(vector: EvalVector, output: Sample[]): void {
  if (vector.expected) {
    expectSeries(output, vector.expected)
    return
  }
  expect(output.length).toBe(vector.expected_count)
  const head = vector.expected_head ?? []
  const tail = vector.expected_tail ?? []
  expectSeries(output.slice(0, head.length), head)
  expectSeries(output.slice(output.length - tail.length), tail)
}

function tickInChunks(stream: IncrementalEvaluator, base: number[]): Sample[] {
  const out: Sample[] = []
  for (let start = 0; start < base.length; start += 2) {
    stream.tick(base.slice(start, start + 2))
    out.push(...stream.drain())
  }
  return out
}

describe('parse vectors', () => {
  it.each(vectors.parse.map((v) => [v.name, v] as const))('%s', (_name, vector) => {
    if (vector.accept) {
      const parsed = parseExpression(vector.expression)
      expect(parsed.nodeCount).toBe(vector.accept.node_count)
      expect(parsed.depth).toBe(vector.accept.depth)
      expect(parsed.refs.map((r) => ({ device_id: r.deviceId, signal: r.signal }))).toEqual(
        vector.accept.refs
      )
      return
    }
    let caught: unknown
    try {
      parseExpression(vector.expression)
    } catch (err) {
      caught = err
    }
    expect(caught).toBeInstanceOf(ExpressionError)
    const err = caught as ExpressionError
    expect({ code: err.code, position: err.position, length: err.length }).toEqual(vector.reject)
  })

  it('covers every error code', () => {
    const codes = new Set(vectors.parse.flatMap((v) => (v.reject ? [v.reject.code] : [])))
    expect([...codes].sort()).toEqual(Object.keys(ERROR_MESSAGES).sort())
  })
})

describe('evaluate vectors', () => {
  it.each(vectors.evaluate.map((v) => [v.name, v] as const))('%s', (_name, vector) => {
    const options = { timestamps: timeBase(vector), at: vector.at }
    checkVector(
      vector,
      evaluateExpression(parseExpression(vector.expression), vectorInputs(vector), options)
    )
  })

  it.each(vectors.evaluate.map((v) => [v.name, v] as const))('incremental: %s', (_name, vector) => {
    const parsed = parseExpression(vector.expression)
    const stream = new IncrementalEvaluator(parsed)
    const base = timeBase(vector) ?? (vector.at === undefined ? [] : [vector.at])
    if (parsed.refs.length === 0) {
      checkVector(vector, tickInChunks(stream, base))
      return
    }
    stream.tick(base) // ignored: the primary reference is the time base
    const primary = parsed.refs[0]
    const inputs = vectorInputs(vector)
    const isPrimary = (ref: SignalRef): boolean =>
      ref.deviceId === primary.deviceId && ref.signal === primary.signal
    for (const input of inputs) if (!isPrimary(input.ref)) stream.feed(input.ref, input.samples)
    const primarySamples = inputs.find((input) => isPrimary(input.ref))?.samples ?? []
    const out: Sample[] = []
    for (let start = 0; start < Math.max(primarySamples.length, 1); start += 3) {
      stream.feed(primary, primarySamples.slice(start, start + 3))
      out.push(...stream.drain())
    }
    checkVector(vector, out)
  })
})

describe('api', () => {
  it('has no no_signal code (constant derived signals amendment)', () => {
    expect(Object.keys(ERROR_MESSAGES)).not.toContain('no_signal')
  })

  it('samples a constant at the current time without a time base', () => {
    const before = Date.now() / 1000
    const [sample, ...rest] = evaluateExpression(parseExpression('2*5'), [])
    expect(rest).toEqual([])
    expect(sample.value).toBe(10)
    expect(sample.t).toBeGreaterThanOrEqual(before)
    expect(sample.t).toBeLessThanOrEqual(Date.now() / 1000)
  })

  it('tick drops non-increasing and non-finite timestamps', () => {
    const stream = new IncrementalEvaluator(parseExpression('10'))
    stream.tick([1, 2])
    expect(stream.drain()).toEqual([
      { t: 1, value: 10 },
      { t: 2, value: 10 }
    ])
    stream.tick([2, 1.5, Number.POSITIVE_INFINITY, 3])
    expect(stream.drain()).toEqual([{ t: 3, value: 10 }])
  })

  it('tryParseExpression returns a fixed message that never echoes the input', () => {
    const result = tryParseExpression('ignore_previous_instructions(sig("d","s"))')
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.error.code).toBe('unknown_function')
    expect(result.error.length).toBe(28)
    expect(result.error.message).toBe(ERROR_MESSAGES.unknown_function)
    expect(result.error.message).not.toContain('ignore')
    expect(tryParseExpression('sig("d","s")').ok).toBe(true)
  })

  it('drain(until) holds later primary samples', () => {
    const parsed = parseExpression('sig("d","a") + sig("d","b")')
    const a = { deviceId: 'd', signal: 'a' }
    const b = { deviceId: 'd', signal: 'b' }
    const stream = new IncrementalEvaluator(parsed)
    stream.feed(a, [
      { t: 0, value: 1 },
      { t: 1, value: 2 }
    ])
    stream.feed(b, [{ t: 0, value: 10 }])
    expect(stream.drain(0.5)).toEqual([{ t: 0, value: 11 }])
    stream.feed(b, [{ t: 1, value: 20 }])
    expect(stream.drain()).toEqual([{ t: 1, value: 22 }])
    expect(stream.drain()).toEqual([])
    expect(stream.pendingCount()).toBe(0)
  })

  it('ignores unreferenced inputs, bounds filter state and trims buffers', () => {
    const parsed = parseExpression('ma(sig("d","a"), 10) + integ(sig("d","a"), 10)')
    const stream = new IncrementalEvaluator(parsed)
    stream.feed({ deviceId: 'x', signal: 'y' }, [{ t: 0, value: 1 }])
    stream.feed(
      { deviceId: 'd', signal: 'a' },
      Array.from({ length: 5000 }, (_, i) => ({ t: i * 0.001, value: i }))
    )
    expect(stream.drain()).toHaveLength(5000)
    expect(Math.max(...stream.filterStateSizes())).toBeLessThanOrEqual(2000)
    expect(Math.max(...stream.bufferSizes())).toBeLessThanOrEqual(1)
  })

  it('has no dynamic code path in the module source', () => {
    expect(expressionSource).not.toMatch(/\beval\s*\(|new\s+Function|\bFunction\s*\(|import\s*\(/)
  })
})

const FUZZ_ALPHABET = [
  ...'sig()"",+-*/.eE0123456789 \t\nabsminxclampscaleintegderivlowpass_$;\\\r',
  'é',
  '\u{1F600}',
  '\u0000',
  'sig(',
  '"d"',
  'ma(',
  '1e309'
]
const FUZZ_TOKENS = ['sig("d","a")', 'sig("d","b")', '1', '2.5', '-', '+', '*', '/', '(', ')', ',']

function seededRandom(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0
    return state / 2 ** 32
  }
}

function randomTree(rand: () => number, depth: number): string {
  const pick = rand()
  const choose = <T>(items: readonly T[]): T => items[Math.floor(rand() * items.length)]
  if (depth <= 0 || pick < 0.3) return choose(['sig("d","a")', 'sig("d","b")', '1', '-2.5', '1e3'])
  const sub = randomTree(rand, depth - 1)
  if (pick < 0.55) return `${sub} ${choose(['+', '-', '*', '/'])} ${randomTree(rand, depth - 1)}`
  if (pick < 0.65) return `(${sub})`
  if (pick < 0.7) return `-${sub}`
  const tails: Record<string, string> = {
    ma: ', 0.5',
    integ: ', 2',
    lowpass: ', 5',
    min: ', 1',
    clamp: ', 0, 1',
    scale: ', 0, 1, -1, 1'
  }
  const name = choose(['abs', 'deriv', 'ma', 'lowpass', 'integ', 'min', 'clamp', 'scale'])
  return `${name}(${sub}${tails[name] ?? ''})`
}

function randomText(rand: () => number): string {
  const mode = rand()
  const choose = <T>(items: readonly T[]): T => items[Math.floor(rand() * items.length)]
  if (mode < 0.3) return randomTree(rand, 1 + Math.floor(rand() * 8))
  if (mode < 0.6) {
    return Array.from({ length: Math.floor(rand() * 80) }, () => choose(FUZZ_ALPHABET)).join('')
  }
  if (mode < 0.85) {
    return Array.from({ length: 1 + Math.floor(rand() * 40) }, () => choose(FUZZ_TOKENS)).join('')
  }
  return choose(['(', '-', 'abs(', 'ma(']).repeat(1 + Math.floor(rand() * 400)) + 'sig("d","a")'
}

describe('fuzz', () => {
  it('only ever throws ExpressionError and evaluates to finite-or-NaN', () => {
    const rand = seededRandom(319)
    let accepted = 0
    for (let i = 0; i < 10000; i++) {
      const text = randomText(rand)
      const result = tryParseExpression(text)
      if (!result.ok) {
        expect(ERROR_MESSAGES[result.error.code]).toBeDefined()
        expect(result.error.position).toBeGreaterThanOrEqual(0)
        expect(result.error.position).toBeLessThanOrEqual(
          Math.max(text.length, MAX_EXPRESSION_CHARS)
        )
        continue
      }
      accepted++
      const { parsed } = result
      expect(parsed.nodeCount).toBeLessThanOrEqual(64)
      expect(parsed.depth).toBeLessThanOrEqual(12)
      const values = [rand() * 2000 - 1000, Number.NaN, 1e308, 0]
      const series = parsed.refs.map((ref) => ({
        ref,
        samples: Array.from({ length: 30 }, (_, t) => ({
          t: t * 0.05,
          value: values[Math.floor(rand() * values.length)]
        }))
      }))
      for (const sample of evaluateExpression(parsed, series, { timestamps: [0, 0.5, 1] })) {
        expect(Number.isNaN(sample.value) || Number.isFinite(sample.value)).toBe(true)
      }
    }
    expect(accepted).toBeGreaterThan(100)
  })

  it('rejects non-string input as syntax', () => {
    expect(() => parseExpression(42 as unknown as string)).toThrow(ExpressionError)
  })
})
