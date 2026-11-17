// Perf marks over the native Performance API (SOLUSDEV-250 P6). Every call is a
// no-op without `performance` (or a missing start mark) — nothing here ever
// throws into a render. Read back with performance.getEntriesByName(<measure>).
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
