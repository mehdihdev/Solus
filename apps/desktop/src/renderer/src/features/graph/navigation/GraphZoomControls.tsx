import { useEffect, useState, type RefObject } from 'react'
import { readGraphZoom, setGraphZoom, stepGraphZoom } from './viewportFraming'

const STEP = 0.1

/** View-only controls remain outside the scaled stage so they are always readable.
 *  The percentage is read back from the stage after every change (and whenever the
 *  level changes, since a new level may auto-fit), never kept as a parallel truth. */
export function GraphZoomControls({
  viewportRef,
  levelKey
}: {
  viewportRef: RefObject<HTMLDivElement | null>
  /** Changes when the shown level changes; re-reads the auto-fit zoom. */
  levelKey: string
}): React.JSX.Element {
  const [zoom, setZoom] = useState(1)
  const sync = (): void => {
    const viewport = viewportRef.current
    if (viewport) setZoom(readGraphZoom(viewport))
  }
  // Passive effect: runs after the navigator's layout effect has applied any auto-fit.
  useEffect(sync, [levelKey]) // eslint-disable-line react-hooks/exhaustive-deps
  const act = (change: (viewport: HTMLElement) => void) => (): void => {
    const viewport = viewportRef.current
    if (!viewport) return
    change(viewport)
    sync()
  }
  return (
    <div className="graph-zoom-controls" role="group" aria-label="Graph zoom">
      <button type="button" aria-label="Zoom out" onClick={act((v) => stepGraphZoom(v, -STEP))}>
        −
      </button>
      <button
        type="button"
        className="graph-zoom-level"
        aria-label="Show graph at 100%"
        title="Reset to 100%"
        onClick={act((v) => setGraphZoom(v, false))}
      >
        {Math.round(zoom * 100)}%
      </button>
      <button type="button" aria-label="Zoom in" onClick={act((v) => stepGraphZoom(v, STEP))}>
        +
      </button>
      <button
        type="button"
        aria-label="Fit graph in view"
        onClick={act((v) => setGraphZoom(v, true))}
      >
        Fit
      </button>
    </div>
  )
}
