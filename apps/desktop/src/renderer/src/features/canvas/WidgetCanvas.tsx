// SOLUSDEV-235 / EXT-15 — the per-project widget canvas (architecture §2
// "Widget canvas"; wireflow docs/wireflows/widget-canvas.md). The first real
// consumer of CTR-01 `discoverWidgets()`: built-in widgets render directly,
// extension widgets through ExtensionFrame in `widget` mode. Focus flows
// through here — a widget reports, the canvas's owner decides (CTR-01).
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Focus, SourceKind, WidgetSlotSize } from '@solus/shared-types'
import { Button } from '../../components/ui/Button'
import { Icons } from '../../components/ui/icons.constants'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'
import { AddWidgetPicker, type DevWidgetEntry } from './AddWidgetPicker'
import { parseWidgetRef, withExtRefs, type AvailableRefs } from './layout'
import { resolveSlotTarget } from './slotTarget'
import { useAvailableWidgets, type AvailableWidgetsDeps } from './useAvailableWidgets'
import { useWidgetLayout, type SaveState, type WidgetLayoutDeps } from './useWidgetLayout'
import { WidgetSlot } from './WidgetSlot'
import { SAVE_TEXT, prunedNote } from './canvasCopy'
import './canvas.css'

export interface WidgetCanvasProps {
  readonly projectId: string
  readonly focus: Focus | null
  readonly onFocusChange: (focus: Focus | null) => void
  /** The screen's own title/focus line, rendered left of the canvas controls. */
  readonly header?: ReactNode
  readonly onOpenStore?: () => void
  /** For the picker's requirement hints; unknown = unmet. */
  readonly connectedKinds?: ReadonlySet<SourceKind> | null
  /** Session-only developer registrations with a widget view (EXT-20): listed
   *  in the picker's Developer section and trusted by the pruner while loaded. */
  readonly dev?: readonly DevWidgetEntry[]
  readonly layoutDeps?: WidgetLayoutDeps
  readonly widgetsDeps?: AvailableWidgetsDeps
}

function SaveNote({
  state,
  onRetry
}: {
  state: SaveState
  onRetry: () => void
}): React.JSX.Element {
  return (
    <span role="status" style={{ fontSize: 11.5, color: 'var(--mut)' }}>
      {SAVE_TEXT[state]}
      {state === 'offline' && (
        <>
          {' · '}
          <button
            type="button"
            onClick={onRetry}
            style={{
              background: 'none',
              border: 0,
              padding: 0,
              font: 'inherit',
              color: 'var(--acc)',
              cursor: 'pointer'
            }}
          >
            Retry
          </button>
        </>
      )}
    </span>
  )
}

function SkeletonGrid(): React.JSX.Element {
  return (
    <div className="widget-canvas-grid" aria-busy="true" data-testid="canvas-skeleton">
      <div className="widget-slot-skeleton" style={{ gridColumn: 'span 3' }} />
      <div className="widget-slot-skeleton" style={{ gridColumn: 'span 1' }} />
    </div>
  )
}

function EmptyCanvas({
  onAdd,
  onRestore
}: {
  onAdd: () => void
  onRestore: () => void
}): React.JSX.Element {
  return (
    <ScreenEmptyState
      icon={<Icons.grid size={30} />}
      title="Nothing on your bench."
      body="Add the Live Bench widget, or any installed extension's widget."
    >
      <div style={{ display: 'flex', gap: 8 }}>
        <Button kind="primary" size="sm" onClick={onAdd}>
          <Icons.plus size={12} /> Add widget
        </Button>
        <Button kind="ghost" size="sm" onClick={onRestore}>
          Restore default
        </Button>
      </div>
    </ScreenEmptyState>
  )
}

/** Scroll a just-added slot into view once it has rendered. */
function useScrollToAdded(
  rootRef: React.RefObject<HTMLDivElement | null>,
  refs: readonly string[]
): (ref: string) => void {
  const pendingRef = useRef<string | null>(null)
  useEffect(() => {
    const ref = pendingRef.current
    if (ref === null || !refs.includes(ref)) return
    pendingRef.current = null
    const el = rootRef.current?.querySelector<HTMLElement>(`[data-ref="${CSS.escape(ref)}"]`)
    el?.scrollIntoView?.({ block: 'nearest' })
  }, [refs, rootRef])
  return useCallback((ref: string) => {
    pendingRef.current = ref
  }, [])
}

const NO_DEV: readonly DevWidgetEntry[] = []

/** The install snapshot plus the dev registrations' slugs — what the pruner may keep. */
function useAvailableRefs(available: AvailableRefs, dev: readonly DevWidgetEntry[]): AvailableRefs {
  return useMemo(() => {
    const slugs = dev.flatMap((entry) => {
      const parsed = parseWidgetRef(entry.ref)
      return parsed?.kind === 'ext' ? [parsed.slug] : []
    })
    return withExtRefs(available, slugs)
  }, [available, dev])
}

export function WidgetCanvas(props: WidgetCanvasProps): React.JSX.Element {
  const { projectId, focus, onFocusChange, header, layoutDeps, widgetsDeps, dev = NO_DEV } = props
  const widgets = useAvailableWidgets(projectId, widgetsDeps)
  const available = useAvailableRefs(widgets.available, dev)
  const layout = useWidgetLayout(projectId, available, layoutDeps)
  const [pickerOpen, setPickerOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const refs = layout.layout.map((s) => s.ref)
  const scrollTo = useScrollToAdded(rootRef, refs)
  const closePicker = useCallback(() => setPickerOpen(false), [])

  const add = (ref: string, size: WidgetSlotSize): void => {
    layout.add(ref, size)
    scrollTo(ref)
  }
  const loading = layout.status === 'loading'

  return (
    <div
      ref={rootRef}
      style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: 'auto', padding: 20 }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
        <div style={{ flex: 1, minWidth: 0 }}>{header}</div>
        {!loading && <SaveNote state={layout.saveState} onRetry={layout.retrySave} />}
        {!loading && (
          <Button kind="ghost" size="sm" onClick={() => setPickerOpen(true)}>
            <Icons.plus size={12} /> Add widget
          </Button>
        )}
      </div>
      {layout.prunedCount > 0 && (
        <p role="status" style={{ fontSize: 11.5, color: 'var(--mut)', margin: '0 0 12px' }}>
          {prunedNote(layout.prunedCount)}
        </p>
      )}

      {loading ? (
        <SkeletonGrid />
      ) : layout.layout.length === 0 ? (
        <EmptyCanvas onAdd={() => setPickerOpen(true)} onRestore={layout.restoreDefault} />
      ) : (
        <div className="widget-canvas-grid" data-testid="widget-canvas-grid">
          {layout.layout.map((slot, i) => {
            const target = resolveSlotTarget(slot.ref, widgets.builtins, widgets.extensions)
            if (target === null) return null
            return (
              <WidgetSlot
                key={slot.ref}
                projectId={projectId}
                slot={slot}
                target={target}
                focus={focus}
                onFocusChange={onFocusChange}
                canMoveLeft={i > 0}
                canMoveRight={i < layout.layout.length - 1}
                onResize={(size) => layout.resize(slot.ref, size)}
                onMove={(direction) => layout.move(slot.ref, direction)}
                onRemove={() => layout.remove(slot.ref)}
              />
            )
          })}
        </div>
      )}

      {pickerOpen && (
        <AddWidgetPicker
          builtins={widgets.builtins}
          extensions={widgets.extensions}
          dev={dev}
          onCanvas={new Set(refs)}
          connectedKinds={props.connectedKinds}
          onAdd={add}
          onClose={closePicker}
          onOpenStore={props.onOpenStore}
        />
      )}
    </div>
  )
}
