// Closed derived-signal grammar for the Live Bench (docs/api/bench-view.md §4;
// architecture/bench-view.md §2): lexer, bounded recursive-descent parser, frozen AST
// and a tree-walking evaluator. Mirrors packages/api/.../livebench/view/expression.py
// rule for rule; both pass packages/shared-types/fixtures/bench-expression-vectors.json.
// Pure module: no React, no store, no dynamic code path. The server's verdict wins.

export const MAX_EXPRESSION_CHARS = 512
export const MAX_NODES = 64
export const MAX_DEPTH = 12
export const MAX_REFS = 8
const MAX_LITERAL_CHARS = 32
const MAX_DEVICE_ID_CHARS = 512
const MAX_SIGNAL_CHARS = 128
const MAX_WINDOW_S = 10
const MAX_CUTOFF_HZ = 1000
export const MAX_FILTER_SAMPLES = 2000
export const HOLD_SECONDS = 1
const DERIV_RESET_S = 1
const LOWPASS_MAX_RESET_S = 10
const MAX_BUFFERED_SAMPLES = 20000

export type ExpressionErrorCode =
  | 'too_long'
  | 'too_many_nodes'
  | 'too_deep'
  | 'too_many_refs'
  | 'no_signal'
  | 'non_finite_literal'
  | 'param_range'
  | 'bad_ref'
  | 'unknown_function'
  | 'arity'
  | 'non_constant_param'
  | 'syntax'

export const ERROR_MESSAGES: Readonly<Record<ExpressionErrorCode, string>> = {
  too_long: 'The expression is longer than 512 characters.',
  too_many_nodes: 'The expression has more than 64 terms.',
  too_deep: 'The expression nests more than 12 levels deep.',
  too_many_refs: 'The expression references more than 8 signals.',
  no_signal: 'The expression must reference at least one signal.',
  non_finite_literal: 'A number is longer than 32 characters or not finite.',
  param_range: 'A filter or scale parameter is out of range.',
  bad_ref: 'A signal reference is empty, too long or has unsupported characters.',
  unknown_function: 'Unknown function.',
  arity: 'A function has the wrong number of arguments.',
  non_constant_param: 'This parameter must be a constant number.',
  syntax: 'The expression does not match the grammar.'
}

/** Parse/bound failure. `message` is fixed per code and never echoes the expression;
 * `position`/`length` are Unicode code-point offsets (same as the server). */
export class ExpressionError extends Error {
  readonly code: ExpressionErrorCode
  readonly position: number
  readonly length: number

  constructor(code: ExpressionErrorCode, position: number, length: number) {
    super(ERROR_MESSAGES[code])
    this.name = 'ExpressionError'
    this.code = code
    this.position = position
    this.length = length
  }
}

export interface SignalRef {
  readonly deviceId: string
  readonly signal: string
}

export interface Sample {
  readonly t: number
  readonly value: number
}

export interface SeriesInput {
  readonly ref: SignalRef
  readonly samples: readonly Sample[]
}

interface Span {
  readonly position: number
  readonly length: number
  readonly height: number
}
export type ExprNode =
  | (Span & { readonly kind: 'number'; readonly value: number })
  | (Span & { readonly kind: 'ref'; readonly ref: SignalRef; readonly index: number })
  | (Span & { readonly kind: 'unary'; readonly operand: ExprNode })
  | (Span & {
      readonly kind: 'binary'
      readonly op: string
      readonly left: ExprNode
      readonly right: ExprNode
    })
  | (Span & {
      readonly kind: 'call'
      readonly name: string
      readonly args: readonly ExprNode[]
      readonly slot: number
    })
  | (Span & { readonly kind: 'group'; readonly inner: ExprNode })

type CallExpr = Extract<ExprNode, { kind: 'call' }>

export interface ParsedExpression {
  readonly root: ExprNode
  readonly nodeCount: number
  readonly depth: number
  /** Distinct, first-appearance order; refs[0] is the time base. */
  readonly refs: readonly SignalRef[]
  readonly filterCount: number
}

const DIGITS = '0123456789'
const IDENT_START = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_'
const PUNCTUATION = '+-*/(),'
const FILTERS = new Set(['ma', 'lowpass', 'deriv', 'integ'])
// name -> [min arity, max arity, constant-only parameter indices]
const FUNCTIONS: ReadonlyMap<string, readonly [number, number, readonly number[]]> = new Map([
  ['abs', [1, 1, []]],
  ['min', [2, 8, []]],
  ['max', [2, 8, []]],
  ['clamp', [3, 3, []]],
  ['scale', [5, 5, [1, 2, 3, 4]]],
  ['ma', [2, 2, [1]]],
  ['lowpass', [2, 2, [1]]],
  ['deriv', [1, 1, []]],
  ['integ', [2, 2, [1]]]
])

// ----------------------------------------------------------------------------- lexer

interface Token {
  readonly kind: string // a PUNCTUATION char, 'num', 'ident', 'str' or 'eof'
  readonly text: string // code points joined
  readonly position: number
  readonly length: number
  readonly value: number
}

const isDigit = (c: string | undefined): boolean =>
  c !== undefined && c.length === 1 && DIGITS.includes(c)
const isIdentStart = (c: string | undefined): boolean =>
  c !== undefined && c.length === 1 && IDENT_START.includes(c)

function token(
  kind: string,
  chars: readonly string[],
  start: number,
  end: number,
  value = 0
): Token {
  return {
    kind,
    text: chars.slice(start, end).join(''),
    position: start,
    length: end - start,
    value
  }
}

function scanDigits(chars: readonly string[], i: number): number {
  while (isDigit(chars[i])) i++
  return i
}

function scanNumber(chars: readonly string[], start: number): number {
  let end = scanDigits(chars, start)
  if (chars[end] === '.') end = scanDigits(chars, end + 1)
  if (chars[end] === 'e' || chars[end] === 'E') {
    let k = end + 1
    if (chars[k] === '+' || chars[k] === '-') k++
    if (isDigit(chars[k])) end = scanDigits(chars, k)
  }
  return end
}

/** Scans the token starting at `i` (never whitespace); returns it with its end. */
function scanToken(chars: readonly string[], i: number): Token {
  const c = chars[i]
  if (c.length === 1 && PUNCTUATION.includes(c)) return token(c, chars, i, i + 1)
  if (isDigit(c) || (c === '.' && isDigit(chars[i + 1]))) return numberToken(chars, i)
  if (isIdentStart(c)) {
    let end = i + 1
    while (isIdentStart(chars[end]) || isDigit(chars[end])) end++
    return token('ident', chars, i, end)
  }
  if (c === '"') {
    const close = chars.indexOf('"', i + 1)
    if (close < 0) throw new ExpressionError('syntax', i, chars.length - i)
    return token('str', chars, i, close + 1)
  }
  throw new ExpressionError('syntax', i, 1)
}

function numberToken(chars: readonly string[], i: number): Token {
  const end = scanNumber(chars, i)
  const literal = chars.slice(i, end).join('')
  const value = literal.length <= MAX_LITERAL_CHARS ? Number(literal) : Infinity
  if (!Number.isFinite(value)) throw new ExpressionError('non_finite_literal', i, end - i)
  return token('num', chars, i, end, value)
}

function lex(chars: readonly string[]): Token[] {
  const tokens: Token[] = []
  let i = 0
  while (i < chars.length) {
    const c = chars[i]
    if (c === ' ' || c === '\t' || c === '\n') {
      i++
      continue
    }
    const next = scanToken(chars, i)
    tokens.push(next)
    i = endOf(next)
  }
  tokens.push(token('eof', chars, chars.length, chars.length))
  return tokens
}

// ---------------------------------------------------------------------------- parser

const spanError = (
  code: ExpressionErrorCode,
  at: { position: number; length: number }
): ExpressionError => new ExpressionError(code, at.position, at.length)
const endOf = (at: { position: number; length: number }): number => at.position + at.length

function refStringOk(content: readonly string[], limit: number): boolean {
  return (
    content.length >= 1 &&
    content.length <= limit &&
    content.every((c) => {
      const code = c.codePointAt(0) ?? 0
      return code >= 0x20 && code <= 0x7e && c !== '"' && c !== '\\'
    })
  )
}

function constantValue(node: ExprNode): number | null {
  if (node.kind === 'number') return node.value
  if (node.kind === 'unary' && node.operand.kind === 'number') return -node.operand.value
  return null
}

function constantParams(call: CallExpr): Map<number, number> {
  const [low, high, constants] = FUNCTIONS.get(call.name) ?? [0, 0, []]
  if (call.args.length < low || call.args.length > high) throw spanError('arity', call)
  const values = new Map<number, number>()
  for (const index of constants) {
    const value = constantValue(call.args[index])
    if (value === null) throw spanError('non_constant_param', call.args[index])
    values.set(index, value)
  }
  return values
}

const inRange = (value: number, max: number): boolean => value > 0 && value <= max

function checkCall(call: CallExpr): void {
  const values = constantParams(call)
  const param = values.get(1) ?? 0
  const windowed = call.name === 'ma' || call.name === 'integ'
  if (windowed && !inRange(param, MAX_WINDOW_S)) throw spanError('param_range', call.args[1])
  if (call.name === 'lowpass' && !inRange(param, MAX_CUTOFF_HZ)) {
    throw spanError('param_range', call.args[1])
  }
  if (call.name === 'scale' && values.get(1) === values.get(2)) {
    throw spanError('param_range', call.args[2])
  }
}

/** Recursive descent; `level` is the nesting level (root = 1). Descending past
 * MAX_DEPTH fails before recursing, so stack use is bounded. */
class Parser {
  private index = 0
  nodeCount = 0
  slotCount = 0
  readonly refs: SignalRef[] = []
  private readonly refKeys: string[] = []

  constructor(private readonly tokens: readonly Token[]) {}

  parse(): ExprNode {
    const root = this.sum(1)
    if (this.peek().kind !== 'eof') throw spanError('syntax', this.peek())
    return root
  }

  private peek(): Token {
    return this.tokens[this.index]
  }

  private next(): Token {
    return this.tokens[this.index++]
  }

  private expect(kind: string): Token {
    if (this.peek().kind !== kind) throw spanError('syntax', this.peek())
    return this.next()
  }

  private static descend(level: number, at: Token): number {
    if (level + 1 > MAX_DEPTH) throw spanError('too_deep', at)
    return level + 1
  }

  private build<N extends ExprNode>(node: N, counted = true): N {
    if (counted && ++this.nodeCount > MAX_NODES) throw spanError('too_many_nodes', node)
    if (node.height > MAX_DEPTH) throw spanError('too_deep', node)
    return node
  }

  private sum(level: number): ExprNode {
    let left = this.product(level)
    while (this.peek().kind === '+' || this.peek().kind === '-') {
      left = this.binary(left, this.next().kind, this.product(level))
    }
    return left
  }

  private product(level: number): ExprNode {
    let left = this.unary(level)
    while (this.peek().kind === '*' || this.peek().kind === '/') {
      left = this.binary(left, this.next().kind, this.unary(level))
    }
    return left
  }

  private binary(left: ExprNode, op: string, right: ExprNode): ExprNode {
    const height = 1 + Math.max(left.height, right.height)
    const length = endOf(right) - left.position
    return this.build({ kind: 'binary', op, left, right, position: left.position, length, height })
  }

  private unary(level: number): ExprNode {
    const at = this.peek()
    if (at.kind !== '-') return this.primary(level)
    const inner = Parser.descend(level, at)
    this.next()
    const operand = this.unary(inner)
    const length = endOf(operand) - at.position
    return this.build({
      kind: 'unary',
      operand,
      position: at.position,
      length,
      height: operand.height + 1
    })
  }

  private primary(level: number): ExprNode {
    const at = this.next()
    if (at.kind === 'num') {
      return this.build({
        kind: 'number',
        value: at.value,
        position: at.position,
        length: at.length,
        height: 1
      })
    }
    if (at.kind === '(') {
      const inner = this.sum(Parser.descend(level, at))
      const close = this.expect(')')
      const group = {
        kind: 'group',
        inner,
        position: at.position,
        length: endOf(close) - at.position
      }
      return this.build({ ...group, kind: 'group', height: inner.height + 1 }, false)
    }
    if (at.kind === 'ident') {
      if (at.text === 'sig') return this.reference(at)
      if (FUNCTIONS.has(at.text)) return this.call(at, level)
      if (this.peek().kind === '(') throw spanError('unknown_function', at)
    }
    throw spanError('syntax', at)
  }

  private refString(limit: number): string {
    const at = this.expect('str')
    const content = Array.from(at.text).slice(1, -1)
    if (!refStringOk(content, limit)) throw spanError('bad_ref', at)
    return content.join('')
  }

  private reference(name: Token): ExprNode {
    this.expect('(')
    const deviceId = this.refString(MAX_DEVICE_ID_CHARS)
    this.expect(',')
    const signal = this.refString(MAX_SIGNAL_CHARS)
    const close = this.expect(')')
    const key = JSON.stringify([deviceId, signal])
    const known = this.refKeys.indexOf(key)
    const index = known >= 0 ? known : this.refKeys.length
    const node = this.build({
      kind: 'ref',
      ref: known >= 0 ? this.refs[known] : { deviceId, signal },
      index,
      position: name.position,
      length: endOf(close) - name.position,
      height: 1
    })
    if (known < 0) {
      if (index === MAX_REFS) throw spanError('too_many_refs', node)
      this.refKeys.push(key)
      this.refs.push(node.ref)
    }
    return node
  }

  private call(name: Token, level: number): ExprNode {
    this.expect('(')
    const inner = Parser.descend(level, name)
    const args = [this.sum(inner)]
    while (this.peek().kind === ',') {
      this.next()
      args.push(this.sum(inner))
    }
    const close = this.expect(')')
    const base = {
      kind: 'call' as const,
      name: name.text,
      args,
      position: name.position,
      length: endOf(close) - name.position,
      height: 1 + Math.max(...args.map((arg) => arg.height))
    }
    checkCall({ ...base, slot: -1 })
    const slot = FILTERS.has(name.text) ? this.slotCount++ : -1
    return this.build({ ...base, slot })
  }
}

/** Parse and bound `text`; throws ExpressionError (never anything else). */
export function parseExpression(text: string): ParsedExpression {
  if (typeof text !== 'string') throw new ExpressionError('syntax', 0, 0)
  const chars = Array.from(text)
  if (chars.length > MAX_EXPRESSION_CHARS) {
    throw new ExpressionError('too_long', MAX_EXPRESSION_CHARS, chars.length - MAX_EXPRESSION_CHARS)
  }
  const parser = new Parser(lex(chars))
  const root = parser.parse()
  if (parser.refs.length === 0) throw new ExpressionError('no_signal', 0, chars.length)
  return {
    root,
    nodeCount: parser.nodeCount,
    depth: root.height,
    refs: [...parser.refs],
    filterCount: parser.slotCount
  }
}

export type ParseResult =
  | { ok: true; parsed: ParsedExpression }
  | { ok: false; error: ExpressionError }

/** Editor-friendly form of parseExpression (inline errors, preview). */
export function tryParseExpression(text: string): ParseResult {
  try {
    return { ok: true, parsed: parseExpression(text) }
  } catch (error) {
    if (error instanceof ExpressionError) return { ok: false, error }
    throw error
  }
}

// ------------------------------------------------------------------------- evaluator

const finite = (value: number): number => (Number.isFinite(value) ? value : Number.NaN)

function foldMin(values: readonly number[]): number {
  if (values.some(Number.isNaN)) return Number.NaN
  let result = values[0]
  for (const v of values.slice(1)) if (v < result) result = v
  return result
}

function foldMax(values: readonly number[]): number {
  if (values.some(Number.isNaN)) return Number.NaN
  let result = values[0]
  for (const v of values.slice(1)) if (v > result) result = v
  return result
}

interface FilterState {
  update(t: number, x: number): number
  size(): number
}

/** Finite samples in (t - w, t], newest MAX_FILTER_SAMPLES; recomputed per sample. */
abstract class WindowedFilter implements FilterState {
  protected samples: Sample[] = []
  private lastT: number | null = null

  constructor(private readonly window: number) {}

  update(t: number, x: number): number {
    if (this.lastT !== null && t - this.lastT > this.window) this.samples = []
    this.lastT = t
    const cutoff = t - this.window
    const kept = Number.isFinite(x) ? [...this.samples, { t, value: x }] : this.samples
    const inWindow = kept.filter((s) => s.t > cutoff)
    this.samples = inWindow.slice(Math.max(0, inWindow.length - MAX_FILTER_SAMPLES))
    return finite(this.reduce())
  }

  size(): number {
    return this.samples.length
  }

  protected abstract reduce(): number
}

class MovingAverage extends WindowedFilter {
  protected reduce(): number {
    if (this.samples.length === 0) return Number.NaN
    let total = 0
    for (const s of this.samples) total += s.value
    return total / this.samples.length
  }
}

class Integral extends WindowedFilter {
  protected reduce(): number {
    let total = 0
    for (let i = 1; i < this.samples.length; i++) {
      const prev = this.samples[i - 1]
      const cur = this.samples[i]
      total += ((cur.t - prev.t) * (cur.value + prev.value)) / 2
    }
    return total
  }
}

class LowPass implements FilterState {
  private readonly rc: number
  private readonly reset: number
  private y: number | null = null
  private tFinite = 0
  private lastT: number | null = null

  constructor(cutoffHz: number) {
    this.rc = 1 / (2 * Math.PI * cutoffHz)
    this.reset = Math.min(LOWPASS_MAX_RESET_S, 5 * this.rc)
  }

  update(t: number, x: number): number {
    if (this.lastT !== null && t - this.lastT > this.reset) this.y = null
    this.lastT = t
    if (!Number.isFinite(x)) return Number.NaN
    if (this.y === null) {
      this.y = x
    } else {
      const dt = t - this.tFinite
      const alpha = dt / (this.rc + dt)
      this.y = this.y + alpha * (x - this.y)
    }
    this.tFinite = t
    return finite(this.y)
  }

  size(): number {
    return this.y === null ? 0 : 1
  }
}

class Derivative implements FilterState {
  private previous: Sample | null = null
  private lastT: number | null = null

  update(t: number, x: number): number {
    if (this.lastT !== null && t - this.lastT > DERIV_RESET_S) this.previous = null
    this.lastT = t
    if (!Number.isFinite(x)) return Number.NaN
    const previous = this.previous
    this.previous = { t, value: x }
    return previous === null ? Number.NaN : finite((x - previous.value) / (t - previous.t))
  }

  size(): number {
    return this.previous === null ? 0 : 1
  }
}

function makeFilter(call: CallExpr): FilterState {
  if (call.name === 'deriv') return new Derivative()
  const parameter = constantValue(call.args[1]) ?? 1
  if (call.name === 'lowpass') return new LowPass(parameter)
  return call.name === 'ma' ? new MovingAverage(parameter) : new Integral(parameter)
}

function filterCalls(node: ExprNode): CallExpr[] {
  switch (node.kind) {
    case 'call': {
      const found = node.args.flatMap(filterCalls)
      return node.slot >= 0 ? [...found, node] : found
    }
    case 'binary':
      return [...filterCalls(node.left), ...filterCalls(node.right)]
    case 'unary':
      return filterCalls(node.operand)
    case 'group':
      return filterCalls(node.inner)
    default:
      return []
  }
}

function upperBound(times: readonly number[], t: number): number {
  let lo = 0
  let hi = times.length
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (times[mid] <= t) lo = mid + 1
    else hi = mid
  }
  return lo
}

/** One reference's accepted samples: strictly increasing finite timestamps. */
class ReferenceBuffer {
  times: number[] = []
  values: number[] = []
  private lastT: number | null = null

  accept(t: number, value: number): boolean {
    if (!Number.isFinite(t) || (this.lastT !== null && t <= this.lastT)) return false
    this.lastT = t
    this.times.push(t)
    this.values.push(Number.isFinite(value) ? value : Number.NaN)
    if (this.times.length > MAX_BUFFERED_SAMPLES) {
      this.times.shift()
      this.values.shift()
    }
    return true
  }

  held(t: number): number {
    const i = upperBound(this.times, t) - 1
    if (i < 0 || t - this.times[i] > HOLD_SECONDS) return Number.NaN
    return this.values[i]
  }

  /** Keep the latest sample at or before `t` and everything after it. */
  trim(t: number): void {
    const i = upperBound(this.times, t) - 1
    if (i > 0) {
      this.times = this.times.slice(i)
      this.values = this.values.slice(i)
    }
  }
}

function binaryOp(op: string, a: number, b: number): number {
  if (op === '+') return finite(a + b)
  if (op === '-') return finite(a - b)
  if (op === '*') return finite(a * b)
  return b === 0 ? Number.NaN : finite(a / b)
}

function applyFunction(name: string, args: readonly number[]): number {
  if (name === 'abs') return finite(Math.abs(args[0]))
  if (name === 'min') return foldMin(args)
  if (name === 'max') return foldMax(args)
  if (name === 'clamp') {
    const [x, low, high] = args
    if (Number.isNaN(low) || Number.isNaN(high) || low > high) return Number.NaN
    return foldMin([foldMax([x, low]), high])
  }
  const [x, inLo, inHi, outLo, outHi] = args // scale
  const span = inHi - inLo
  return span === 0 ? Number.NaN : finite(outLo + ((x - inLo) * (outHi - outLo)) / span)
}

const refKey = (ref: SignalRef): string => JSON.stringify([ref.deviceId, ref.signal])

/** Streaming evaluation with bounded state; outputs at the primary's timestamps.
 * `drain` equals a batch run provided every secondary sample with timestamp <= t was
 * fed before t is drained. */
export class IncrementalEvaluator {
  private readonly index: ReadonlyMap<string, number>
  private readonly buffers: ReferenceBuffer[]
  private readonly filters: FilterState[]
  private pending: number[] = []

  constructor(private readonly parsed: ParsedExpression) {
    this.index = new Map(parsed.refs.map((ref, i) => [refKey(ref), i]))
    this.buffers = parsed.refs.map(() => new ReferenceBuffer())
    this.filters = filterCalls(parsed.root)
      .sort((a, b) => a.slot - b.slot)
      .map(makeFilter)
  }

  feed(ref: SignalRef, samples: readonly Sample[]): void {
    const index = this.index.get(refKey(ref))
    if (index === undefined) return
    const buffer = this.buffers[index]
    for (const sample of samples) {
      if (buffer.accept(sample.t, sample.value) && index === 0) this.pending.push(sample.t)
    }
    if (this.pending.length > MAX_BUFFERED_SAMPLES) {
      this.pending = this.pending.slice(this.pending.length - MAX_BUFFERED_SAMPLES)
    }
  }

  drain(until?: number): Sample[] {
    const out: Sample[] = []
    let taken = 0
    while (taken < this.pending.length && (until === undefined || this.pending[taken] <= until)) {
      const t = this.pending[taken++]
      const held = this.buffers.map((buffer) => buffer.held(t))
      out.push({ t, value: this.value(this.parsed.root, t, held) })
    }
    this.pending = this.pending.slice(taken)
    const last = out.at(-1)
    if (last) for (const buffer of this.buffers) buffer.trim(last.t)
    return out
  }

  pendingCount(): number {
    return this.pending.length
  }

  /** Newest primary timestamp still waiting to be drained, or null. */
  newestPending(): number | null {
    return this.pending.at(-1) ?? null
  }

  filterStateSizes(): number[] {
    return this.filters.map((state) => state.size())
  }

  bufferSizes(): number[] {
    return this.buffers.map((buffer) => buffer.times.length)
  }

  private value(node: ExprNode, t: number, held: readonly number[]): number {
    switch (node.kind) {
      case 'number':
        return node.value
      case 'ref':
        return held[node.index]
      case 'group':
        return this.value(node.inner, t, held)
      case 'unary':
        return finite(-this.value(node.operand, t, held))
      case 'binary':
        return binaryOp(node.op, this.value(node.left, t, held), this.value(node.right, t, held))
      case 'call': {
        // Every argument is evaluated (no short-circuit) so nested filters advance.
        const args = node.args.map((arg) => this.value(arg, t, held))
        return node.slot >= 0
          ? this.filters[node.slot].update(t, args[0])
          : applyFunction(node.name, args)
      }
    }
  }
}

/** Batch evaluation: samples at the primary timestamps; NaN marks a gap. */
export function evaluateExpression(
  parsed: ParsedExpression,
  series: readonly SeriesInput[]
): Sample[] {
  const stream = new IncrementalEvaluator(parsed)
  for (const input of series) stream.feed(input.ref, input.samples)
  return stream.drain()
}
