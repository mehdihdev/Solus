// SOLUSDEV-319: the Ember Pill's panel (Guide tasks, the thread, the region
// card) above the bar. The section's height is set explicitly from its body's
// measured natural height so a CSS transition animates every change — opening
// from zero, growing as messages and plan cards arrive, shrinking — while the
// body stays bottom-aligned inside it (content unrolls upward with the window).
import { useLayoutEffect, useRef, useState } from 'react'

const canObserve = (): boolean => typeof ResizeObserver !== 'undefined'

function useContentHeight(ref: React.RefObject<HTMLDivElement | null>): number | undefined {
  const [height, setHeight] = useState<number | undefined>(() => (canObserve() ? 0 : undefined))
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || !canObserve()) return
    const observer = new ResizeObserver(() => {
      setHeight(Math.ceil(el.getBoundingClientRect().height))
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref])
  return height
}

export function PillPanel({ children }: { children: React.ReactNode }): React.JSX.Element {
  const bodyRef = useRef<HTMLDivElement>(null)
  const height = useContentHeight(bodyRef)
  return (
    <section
      className="sol-pill-panel"
      aria-label="SOL conversation"
      style={height === undefined ? undefined : { height }}
    >
      <div className="sol-pill-panel-body" ref={bodyRef}>
        {children}
      </div>
    </section>
  )
}
