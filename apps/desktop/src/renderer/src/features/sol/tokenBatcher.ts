// SOLUSDEV-252 S2-A: coalesce streamed token text into ONE flush per animation
// frame. Pure scheduler — no store, no React. The store owns ordering: every
// non-token event calls flushNow() first so tool/message/error frames can
// never overtake the prose they follow.

/** rAF when the window has one; a ~frame timer otherwise (tests, hidden
 *  windows). ponytail: rAF pauses while the window is hidden — text simply
 *  lands on the next frame or the next non-token event; nothing is lost. */
const defaultSchedule = (cb: () => void): void => {
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(cb)
  else setTimeout(cb, 16)
}

export interface TokenBatcher {
  push: (text: string) => void
  /** Deliver pending text synchronously (ordering before any other event). */
  flushNow: () => void
  /** Drop pending text and ignore everything after. */
  dispose: () => void
}

/** `maxChars` caps the in-flight buffer (SEC-H3): it can never usefully exceed
 *  the per-turn ceiling the flush target enforces. */
export function createTokenBatcher(
  flush: (text: string) => void,
  schedule: (cb: () => void) => void = defaultSchedule,
  maxChars = Infinity
): TokenBatcher {
  let buffer = ''
  let scheduled = false
  let disposed = false
  const flushNow = (): void => {
    scheduled = false
    if (buffer === '') return
    const text = buffer
    buffer = ''
    flush(text)
  }
  return {
    push: (text) => {
      if (disposed || buffer.length >= maxChars) return
      buffer += text
      if (scheduled) return
      scheduled = true
      schedule(flushNow)
    },
    flushNow,
    dispose: () => {
      disposed = true
      buffer = ''
    }
  }
}
