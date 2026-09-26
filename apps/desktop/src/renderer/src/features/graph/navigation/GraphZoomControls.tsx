import type { RefObject } from 'react'
import { setGraphZoom } from './viewportFraming'

/** View-only controls remain outside the scaled stage so they are always readable. */
export function GraphZoomControls({
  viewportRef
}: {
  viewportRef: RefObject<HTMLDivElement | null>
}): React.JSX.Element {
  const zoom = (fit: boolean): void => {
    const viewport = viewportRef.current
    if (viewport) setGraphZoom(viewport, fit)
  }
  return (
    <div className="graph-zoom-controls" role="group" aria-label="Graph zoom">
      <button type="button" aria-label="Fit graph in view" onClick={() => zoom(true)}>
        Fit
      </button>
      <button type="button" aria-label="Show graph at 100%" onClick={() => zoom(false)}>
        100%
      </button>
    </div>
  )
}
