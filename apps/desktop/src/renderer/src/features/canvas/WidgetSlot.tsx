// SOLUSDEV-235 / EXT-15 — one canvas slot: the 32 px chrome (title, state dot,
// mono size, menu, remove) over the widget body. Built-ins render directly with
// CTR-01 `WidgetProps`; extension widgets render ONLY through ExtensionFrame in
// `widget` mode — nothing from an extension is placed into host DOM here.
import { useState } from 'react'
import type { Focus, WidgetRenderState } from '@solus/shared-types'
import { Icons } from '../../components/ui/icons.constants'
import { Mono } from '../../components/ui/Mono'
import { ExtensionFrame } from '../extensions/frame/ExtensionFrame'
import { ExtensionIcon } from '../extensions/host/ExtensionIcon'
import { useExtensionIconSvg } from '../extensions/pageview/extensionIconAsset'
import { slotSpan, type LayoutSlot } from './layout'
import { SlotMenu, type SlotMenuProps } from './SlotMenu'
import { slotSizeHint, slotTitle, type SlotTarget } from './slotTarget'
import type { ExtensionWidgetEntry } from './useAvailableWidgets'

type MenuControls = Pick<SlotMenuProps, 'canMoveLeft' | 'canMoveRight' | 'onResize' | 'onMove'>

export interface WidgetSlotProps extends MenuControls {
  readonly projectId: string
  readonly slot: LayoutSlot
  readonly target: SlotTarget
  readonly focus: Focus | null
  readonly onFocusChange: (focus: Focus | null) => void
  readonly onRemove: () => void
}

const REMOVE_STYLE: React.CSSProperties = {
  display: 'inline-flex',
  padding: 4,
  background: 'transparent',
  border: 0,
  borderRadius: 3,
  color: 'var(--mut)',
  cursor: 'pointer'
}

/** The chrome's read of `onStateChange`: a muted dot while loading, a warn dot on error. */
function StateDot({ state }: { state: WidgetRenderState | null }): React.JSX.Element | null {
  if (state !== 'loading' && state !== 'error') return null
  const isError = state === 'error'
  return (
    <span
      role="img"
      aria-label={isError ? 'Widget error' : 'Widget loading'}
      title={isError ? 'This widget hit an error' : 'Loading'}
      data-testid="slot-state"
      data-state={state}
      style={{
        width: 7,
        height: 7,
        borderRadius: '50%',
        flex: 'none',
        background: isError ? 'var(--warn)' : 'var(--mut)',
        opacity: isError ? 1 : 0.6
      }}
    />
  )
}

function ExtensionMark({ entry }: { entry: ExtensionWidgetEntry }): React.JSX.Element {
  const svg = useExtensionIconSvg(entry.slug, entry.version, entry.iconPath)
  return <ExtensionIcon svg={svg} size={14} />
}

function SlotBody(props: {
  target: SlotTarget
  projectId: string
  focus: Focus | null
  onFocusChange: (focus: Focus | null) => void
  onStateChange: (state: WidgetRenderState) => void
}): React.JSX.Element {
  const { target, projectId, focus, onFocusChange, onStateChange } = props
  if (target.kind === 'builtin') {
    const Component = target.entry.component
    return <Component focus={focus} onFocusChange={onFocusChange} onStateChange={onStateChange} />
  }
  return (
    <ExtensionFrame
      projectId={projectId}
      slug={target.slug}
      view="widget"
      onStateChange={onStateChange}
    />
  )
}

export function WidgetSlot(props: WidgetSlotProps): React.JSX.Element {
  const { projectId, slot, target, focus, onFocusChange, onRemove } = props
  const [state, setState] = useState<WidgetRenderState | null>(null)
  const title = slotTitle(target)
  const span = slotSpan(slot.size)

  return (
    <section
      className="widget-slot screen-in"
      data-testid="widget-slot"
      data-ref={slot.ref}
      data-span={span}
      aria-label={title}
      style={{ '--span': span } as React.CSSProperties}
    >
      <div className="widget-slot-chrome">
        {target.kind === 'ext' && target.entry !== null && <ExtensionMark entry={target.entry} />}
        <span
          style={{
            fontSize: 12.5,
            fontWeight: 600,
            color: 'var(--tx)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap'
          }}
        >
          {title}
        </span>
        <StateDot state={state} />
        <span style={{ flex: 1 }} />
        <Mono size={9}>{slot.size}</Mono>
        <SlotMenu
          title={title}
          size={slot.size}
          hint={slotSizeHint(target)}
          canMoveLeft={props.canMoveLeft}
          canMoveRight={props.canMoveRight}
          onResize={props.onResize}
          onMove={props.onMove}
        />
        <button
          type="button"
          className="interactive"
          style={REMOVE_STYLE}
          aria-label={`Remove ${title}`}
          onClick={onRemove}
        >
          <Icons.x size={12} />
        </button>
      </div>
      <div className="widget-slot-body">
        <SlotBody
          target={target}
          projectId={projectId}
          focus={focus}
          onFocusChange={onFocusChange}
          onStateChange={setState}
        />
      </div>
    </section>
  )
}
