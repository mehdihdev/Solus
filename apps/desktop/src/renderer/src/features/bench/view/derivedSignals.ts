// Live evaluation of the project's derived signals over the device series the Live
// Bench already retains (retainedSignals.ts), using the closed grammar evaluator
// (expression.ts; docs/api/bench-view.md §4, architecture/bench-view.md §2).
// Each poll re-feeds the retained window; the evaluator drops samples it has already
// seen, so filter state carries across polls. Pure: no React, no store access.
import type { BenchDeviceRecent, BenchSignalPoint } from '../../../lib/api/resources'
import {
  ExpressionError,
  HOLD_SECONDS,
  IncrementalEvaluator,
  evaluateExpression,
  tryParseExpression,
  type ParsedExpression,
  type Sample,
  type SignalRef
} from './expression'

/** Newest derived samples kept per signal (matches the filter sample cap). */
export const MAX_DERIVED_POINTS = 2000

export interface DerivedDefinition {
  readonly id: string
  readonly name: string
  readonly expression: string
  readonly unit: string | null
}

/** One derived series; a NaN `value` is a gap (render as a break, never as zero). */
export interface DerivedSeries {
  readonly id: string
  readonly name: string
  readonly unit: string | null
  readonly points: readonly BenchSignalPoint[]
  readonly error: ExpressionError | null
}

type Devices = Readonly<Record<string, BenchDeviceRecent>>

function seriesSamples(devices: Devices, ref: SignalRef): Sample[] {
  const device = Object.hasOwn(devices, ref.deviceId) ? devices[ref.deviceId] : undefined
  const series = device?.signals.find((s) => s.signal === ref.signal)
  return (series?.points ?? []).flatMap((point) => {
    const t = Date.parse(point.timestamp) / 1000
    return Number.isFinite(t) ? [{ t, value: point.value }] : []
  })
}

const toPoint = (sample: Sample): BenchSignalPoint => ({
  timestamp: new Date(sample.t * 1000).toISOString(),
  value: sample.value
})

interface StreamEntry {
  readonly expression: string
  readonly parsed: ParsedExpression | null
  readonly error: ExpressionError | null
  readonly evaluator: IncrementalEvaluator | null
  points: BenchSignalPoint[]
}

function createEntry(expression: string): StreamEntry {
  const result = tryParseExpression(expression)
  return result.ok
    ? {
        expression,
        parsed: result.parsed,
        error: null,
        evaluator: new IncrementalEvaluator(result.parsed),
        points: []
      }
    : { expression, parsed: null, error: result.error, evaluator: null, points: [] }
}

/** A primary sample at t is released once every secondary has data at or after t,
 * or once t is older than the newest primary sample by the hold window (a secondary
 * that late reads as stale anyway). */
function releaseHorizon(
  parsed: ParsedExpression,
  samples: readonly Sample[][],
  newestPrimary: number | null
): number | undefined {
  if (parsed.refs.length === 1 || newestPrimary === null) return undefined
  const horizons = samples.slice(1).map((list) => {
    const newest = list.at(-1)?.t ?? Number.NEGATIVE_INFINITY
    return Math.max(newest, newestPrimary - HOLD_SECONDS)
  })
  return Math.min(...horizons)
}

export class DerivedSignalStream {
  private entries = new Map<string, StreamEntry>()

  constructor(private readonly maxPoints = MAX_DERIVED_POINTS) {}

  /** Feed the latest retained devices; returns one series per definition, in order. */
  update(definitions: readonly DerivedDefinition[], devices: Devices): DerivedSeries[] {
    const next = new Map<string, StreamEntry>()
    const result = definitions.map((definition) => {
      const known = this.entries.get(definition.id)
      const entry =
        known && known.expression === definition.expression
          ? known
          : createEntry(definition.expression)
      next.set(definition.id, entry)
      this.advance(entry, devices)
      return {
        id: definition.id,
        name: definition.name,
        unit: definition.unit,
        points: [...entry.points],
        error: entry.error
      }
    })
    this.entries = next
    return result
  }

  /** Number of definitions currently tracked. */
  size(): number {
    return this.entries.size
  }

  private advance(entry: StreamEntry, devices: Devices): void {
    const { parsed, evaluator } = entry
    if (!parsed || !evaluator) return
    const samples = parsed.refs.map((ref) => seriesSamples(devices, ref))
    // Secondaries first so their samples are known before primary times are drained.
    samples.forEach((list, i) => {
      if (i > 0) evaluator.feed(parsed.refs[i], list)
    })
    evaluator.feed(parsed.refs[0], samples[0])
    const drained = evaluator.drain(releaseHorizon(parsed, samples, evaluator.newestPending()))
    if (drained.length === 0) return
    const merged = [...entry.points, ...drained.map(toPoint)]
    entry.points = merged.slice(Math.max(0, merged.length - this.maxPoints))
  }
}

export interface DerivedPreview {
  readonly points: readonly BenchSignalPoint[]
  readonly error: ExpressionError | null
}

/** Editor preview: parse a draft and evaluate it over the retained data in one batch. */
export function previewDerivedSignal(expression: string, devices: Devices): DerivedPreview {
  const result = tryParseExpression(expression)
  if (!result.ok) return { points: [], error: result.error }
  const series = result.parsed.refs.map((ref) => ({ ref, samples: seriesSamples(devices, ref) }))
  const points = evaluateExpression(result.parsed, series).map(toPoint)
  return { points: points.slice(Math.max(0, points.length - MAX_DERIVED_POINTS)), error: null }
}
