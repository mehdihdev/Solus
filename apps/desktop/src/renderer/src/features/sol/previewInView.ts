// SOLUSDEV-317 (Phase 4 M1): a command card's Cmd/Ctrl+Enter arming clock
// starts only once its verbatim preview is actually on screen
// (sol-page.md "Command preview is open"). The observer is a context seam so
// jsdom tests (no IntersectionObserver) can drive visibility directly.
import { createContext, useContext, useEffect, useState } from 'react'
import { CommandApprovalContext } from './commandHotkey'

/** At least this fraction of the bounded preview region must be visible. */
export const IN_VIEW_RATIO = 0.5

/** Watch an element; report whether it is in view. Returns the disconnect. */
export type ObserveInView = (element: Element, onChange: (inView: boolean) => void) => () => void

/** The real observer. Without IntersectionObserver nothing is ever reported in
 *  view, so the shortcut fails closed (the Approve button still works). */
export const observeInView: ObserveInView = (element, onChange) => {
  if (typeof IntersectionObserver === 'undefined') return () => undefined
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        onChange(entry.isIntersecting && entry.intersectionRatio >= IN_VIEW_RATIO)
      }
    },
    { threshold: [0, IN_VIEW_RATIO] }
  )
  observer.observe(element)
  return () => observer.disconnect()
}

export const PreviewObserverContext = createContext<ObserveInView>(observeInView)

/** Feed a command card's preview visibility to the surface's arming clock.
 *  Returns the callback ref for the preview region; pass `enabled: false` for
 *  non-command cards. Unmounting forgets the clock. */
export function usePreviewInView(
  confirmationId: string,
  enabled: boolean
): (element: HTMLElement | null) => void {
  const registry = useContext(CommandApprovalContext)
  const observe = useContext(PreviewObserverContext)
  const [element, setElement] = useState<HTMLElement | null>(null)
  useEffect(() => {
    if (!enabled || !registry || !element) return
    const stop = observe(element, (inView) => registry.setInView(confirmationId, inView))
    return () => {
      stop()
      registry.forgetView(confirmationId)
    }
  }, [enabled, registry, observe, element, confirmationId])
  return setElement
}
