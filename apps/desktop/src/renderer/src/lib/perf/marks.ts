// Perf marks over the native Performance API (SOLUSDEV-250 P6). Every call is a
// no-op without `performance` (or a missing start mark) — nothing here ever
// throws into a render. Read back with performance.getEntriesByName(<measure>).
const marked = new Set<string>()
const awaited = new Map<string, string | undefined>()
const arrivals = new Map<string, { start: string; rendered: boolean }>()
let sequence = 0

export function markSafely(name: string): void {
  try {
    performance.mark(name)
  } catch {
    /* no Performance API */
  }
}

export function measureSafely(name: string, start: string, end: string): void {
  try {
    performance.measure(name, start, end)
  } catch {
    /* a start mark that never fired */
  }
}

/** Mark `name` the first time `key` is seen — a card that remounts marks once. */
export function markOnce(name: string, key: string): boolean {
  const seen = `${name}:${key}`
  if (marked.has(seen)) return false
  marked.add(seen)
  markSafely(name)
  return true
}

/** Register a key whose arrival `markAwaited` marks (a confirmed robot's id). */
export function awaitMark(key: string, start?: string): void {
  awaited.set(key, start)
}

export function markAwaited(name: string, key: string): boolean {
  if (!awaited.has(key)) return false
  const start = awaited.get(key)
  awaited.delete(key)
  const end = start ? `${name}:${key}` : name
  markSafely(end)
  if (start) measureSafely(`hw:confirm_to_node:${key}`, start, end)
  return true
}

/** Test seam. */
export function resetMarks(): void {
  marked.clear()
  awaited.clear()
  arrivals.clear()
}

/** One start per submitted confirmation; concurrent responses cannot share a clock. */
export function startConfirmation(): string {
  const name = `hw:confirm_sent:${++sequence}`
  markSafely(name)
  return name
}

/** Full local lists delimit appearances. This measures receipt, never physical insertion. */
export function recordDeviceFrame(refs: readonly string[]): void {
  const present = new Set(refs)
  for (const key of arrivals.keys()) if (!present.has(key)) arrivals.delete(key)
  for (const key of present) {
    if (arrivals.has(key)) continue
    const start = `hw:frame_received:${++sequence}`
    markSafely(start)
    arrivals.set(key, { start, rendered: false })
  }
}

export function markDeviceRendered(ref: string): void {
  const arrival = arrivals.get(ref)
  if (!arrival || arrival.rendered) return
  arrival.rendered = true
  const end = `${arrival.start}:rendered`
  markSafely(end)
  measureSafely(`hw:receipt_to_card:${ref}`, arrival.start, end)
}
