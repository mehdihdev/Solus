// Scroll-spy for the Settings sidebar (SOLUSDEV-318): which section anchor is
// the topmost one in the upper part of the viewport. Null where there is no
// IntersectionObserver (jsdom), so the sidebar simply highlights nothing.
import { useEffect, useState } from 'react'

/** Watch the upper ~third of the scroll area. */
const ROOT_MARGIN = '0px 0px -65% 0px'

export function useActiveSection(anchors: readonly string[]): string | null {
  const [active, setActive] = useState<string | null>(null)
  const key = anchors.join('|')
  useEffect(() => {
    if (typeof IntersectionObserver !== 'function') return
    const ids = key ? key.split('|') : []
    const visible = new Set<string>()
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const id = (e.target as Element).id
          if (e.isIntersecting) visible.add(id)
          else visible.delete(id)
        }
        // Document order, not callback order, decides "topmost".
        const top = ids.find((id) => visible.has(id))
        if (top) setActive(top)
      },
      { rootMargin: ROOT_MARGIN }
    )
    for (const id of ids) {
      const el = document.getElementById(id)
      if (el) observer.observe(el)
    }
    return () => observer.disconnect()
  }, [key])
  return active
}
