// SOLUSDEV-216 (CTR-01) — the reference widget.
//
// It exists to prove one claim: a lane can build a widget with NO CANVAS in the
// repo. Nothing here imports a canvas, a layout, or the workspace shell — only
// the contract. It also demonstrates all four render states and the
// focus-change callback, so a lane has a worked example rather than prose.
//
// Owned by LANE 0. A feature lane copies this directory's SHAPE, not this file.
import { useEffect, useState } from 'react'
import { descend, type Focus, type WidgetProps, type WidgetRenderState } from '@solus/shared-types'

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * Stands in for the real work a widget does when focus changes — a graph read,
 * a checker run, a telemetry subscription. Async and fallible on purpose: those
 * are the two properties that make `loading` and `error` real states rather
 * than decoration.
 */
async function describeEntity(focus: Focus): Promise<string> {
  if (!UUID_RE.test(focus.entity.entityId)) {
    throw new Error(`not a graph entity id: ${focus.entity.entityId}`)
  }
  return focus.label ?? focus.entity.entityId
}

export function ReferenceWidget({
  focus,
  onFocusChange,
  onStateChange
}: WidgetProps): React.JSX.Element {
  const { state, description } = useEntityDescription(focus, onStateChange)

  if (state === 'empty') {
    return (
      <p role="status" style={{ color: 'var(--mut)' }}>
        Nothing focused yet — pick an entity to inspect.
      </p>
    )
  }

  if (state === 'loading') {
    return (
      <p role="status" style={{ color: 'var(--mut)' }}>
        Loading…
      </p>
    )
  }

  if (state === 'error' || focus === null) {
    return (
      <p role="alert" style={{ color: 'var(--mut)' }}>
        Could not describe this entity.
      </p>
    )
  }

  return (
    <div>
      <p className="font-mono">{description}</p>
      <p style={{ color: 'var(--mut)' }}>{focus.domain}</p>
      <button
        type="button"
        onClick={() =>
          // A widget NEVER writes to the focus store. It reports the change and
          // the canvas decides — which is what keeps focus routable and loggable.
          onFocusChange(
            descend(focus, {
              entity: {
                projectId: focus.entity.projectId,
                entityId: 'aaaa1111-0000-0000-0000-0000000000ff'
              },
              domain: 'electrical',
              label: 'driver',
              relation: 'drives'
            })
          )
        }
      >
        Follow &quot;drives&quot;
      </button>
    </div>
  )
}

function useEntityDescription(
  focus: WidgetProps['focus'],
  onStateChange: WidgetProps['onStateChange']
) {
  const [state, setState] = useState<WidgetRenderState>(focus === null ? 'empty' : 'loading')
  const [description, setDescription] = useState<string | null>(null)

  useEffect(() => {
    if (focus === null) {
      setState('empty')
      setDescription(null)
      return
    }
    // A focus change can land while the previous read is in flight; without the
    // guard the slower one wins and the widget shows the wrong entity.
    let live = true
    setState('loading')
    describeEntity(focus)
      .then((text) => {
        if (!live) return
        setDescription(text)
        setState('ready')
      })
      .catch(() => {
        if (!live) return
        setDescription(null)
        setState('error')
      })
    return () => {
      live = false
    }
  }, [focus])

  // Reported in its own effect so the canvas sees every transition exactly once,
  // including the ones that happen inside the async read above.
  useEffect(() => onStateChange?.(state), [state, onStateChange])

  return { state, description }
}
