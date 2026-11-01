// Pure helpers behind the derived-signal editor (wireflow live-bench-view.md §2): the error
// span to underline, quoted reference insertion, the streaming signals a draft may name,
// and the references with no data yet. Offsets are Unicode code points, as the parsers use.
import type { BenchDeviceRecent, BenchSignalSeries } from '../../../lib/api/resources'
import type { DerivedSeries } from './derivedSignals'
import type { SignalRef } from './expression'

export interface ErrorSpan {
  position: number
  length: number
  message: string
}

export interface SplitText {
  before: string
  marked: string
  after: string
}

/** Split the draft around an error; a zero-length span marks one character (or a space at the end). */
export function splitAtError(text: string, span: ErrorSpan): SplitText {
  const chars = Array.from(text)
  const start = Math.min(Math.max(span.position, 0), chars.length)
  const end = Math.min(start + Math.max(span.length, 1), chars.length)
  const marked = chars.slice(start, end).join('')
  return {
    before: chars.slice(0, start).join(''),
    marked: marked || ' ',
    after: chars.slice(end).join('')
  }
}

/** The reference charset (route doc §1): printable ASCII except `"` and `\`. */
const REFERENCEABLE = /^[\x20-\x21\x23-\x5B\x5D-\x7E]+$/

export const referenceText = (ref: SignalRef): string => `sig("${ref.deviceId}", "${ref.signal}")`

/** Streaming signals that can be written as a reference, by device then signal name. */
export function streamingSignals(
  devices: Readonly<Record<string, BenchDeviceRecent>>
): SignalRef[] {
  return Object.values(devices)
    .flatMap((device) =>
      device.signals.map((series) => ({ deviceId: device.device_id, signal: series.signal }))
    )
    .filter((ref) => REFERENCEABLE.test(ref.deviceId) && REFERENCEABLE.test(ref.signal))
    .sort((a, b) => a.deviceId.localeCompare(b.deviceId) || a.signal.localeCompare(b.signal))
}

export function missingRefs(
  refs: readonly SignalRef[],
  devices: Readonly<Record<string, BenchDeviceRecent>>
): SignalRef[] {
  return refs.filter((ref) => {
    const device = Object.hasOwn(devices, ref.deviceId) ? devices[ref.deviceId] : undefined
    return !device?.signals.some((series) => series.signal === ref.signal && series.points.length)
  })
}

/** Insert at a UTF-16 caret (what a textarea reports) and return the new caret too. */
export function insertAt(
  text: string,
  caret: number | null,
  insert: string
): { text: string; caret: number } {
  const at = caret === null ? text.length : Math.min(Math.max(caret, 0), text.length)
  return { text: text.slice(0, at) + insert + text.slice(at), caret: at + insert.length }
}

/** A derived series as a card series: the derived unit on every point; NaN stays a gap. */
export function derivedCardSeries(
  series: DerivedSeries | undefined,
  name: string
): BenchSignalSeries {
  return {
    signal: name,
    points: (series?.points ?? []).map((point) => ({ ...point, unit: series?.unit ?? null }))
  }
}
