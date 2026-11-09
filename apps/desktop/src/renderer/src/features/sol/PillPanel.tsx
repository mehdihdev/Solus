// SOLUSDEV-319: the Ember Pill's panel (Guide tasks, the thread, the region
// card) above the bar. The section's height follows its body's measured natural
// height through a critically damped spring (pillSpring.ts), written straight to
// the element each frame — opening from zero, growing as a reply streams in,
// shrinking — while the body stays bottom-aligned inside it (content unrolls
// upward with the window). Retargeting keeps velocity, so a stream of small
// growths is one continuous motion. Reduced motion jumps straight to the height.
import { useLayoutEffect, useRef } from 'react'
import { settle, stepSpring, type SpringState } from './pillSpring'

const canObserve = (): boolean => typeof ResizeObserver !== 'undefined'
const prefersReducedMotion = (): boolean =>
  typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
const FRAME_S = 1 / 60

function useSpringHeight(
  panelRef: React.RefObject<HTMLElement | null>,
  bodyRef: React.RefObject<HTMLDivElement | null>
): void {
  useLayoutEffect(() => {
    const panel = panelRef.current
    const body = bodyRef.current
    if (!panel || !body || !canObserve()) return
    let state: SpringState = { x: 0, v: 0 }
    let target = 0
    let frame: number | null = null
    let last: number | null = null
    const paint = (): void => void (panel.style.height = `${Math.max(0, state.x)}px`)
    const tick = (time: number): void => {
      const dt = last === null ? FRAME_S : (time - last) / 1000
      last = time
      const next = stepSpring(state, target, dt)
      const done = settle(next, target)
      state = done ?? next
      paint()
      frame = done ? null : requestAnimationFrame(tick)
      if (done) last = null
    }
    paint()
    const observer = new ResizeObserver(() => {
      target = Math.ceil(body.getBoundingClientRect().height)
      if (prefersReducedMotion() || typeof requestAnimationFrame !== 'function') {
        state = { x: target, v: 0 }
        return paint()
      }
      // Idle stays frame-free (the SOL window perf budget): only a real move runs.
      if (frame === null && settle(state, target) === null) frame = requestAnimationFrame(tick)
    })
    observer.observe(body)
    return () => {
      observer.disconnect()
      if (frame !== null) cancelAnimationFrame(frame)
    }
  }, [panelRef, bodyRef])
}

export function PillPanel({ children }: { children: React.ReactNode }): React.JSX.Element {
  const panelRef = useRef<HTMLElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  useSpringHeight(panelRef, bodyRef)
  return (
    <section className="sol-pill-panel" aria-label="SOL conversation" ref={panelRef}>
      <div className="sol-pill-panel-body" ref={bodyRef}>
        {children}
      </div>
    </section>
  )
}
