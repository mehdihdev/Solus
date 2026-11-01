// The ⋯ menu on a signal card or derived row (wireflow live-bench-view.md §1, §8): Pin/Unpin,
// Hide, Move, Unit (packet-unit family only), Axis range, Plot group; Edit/Delete on derived
// rows. A viewer sees only "Copy expression" on derived rows and no menu on signal cards.
// Every label is rendered as escaped text (team-authored data).
import { useState } from 'react'
import {
  BENCH_VIEW_LIMITS,
  type BenchViewDisplayPatch,
  type BenchViewTarget
} from '@solus/shared-types'
import { unitOptions } from '../signalUnits'
import { useBenchViewContext } from './BenchViewContext'
import { useBenchViewStore } from './useBenchView'
import { plotGroups } from './viewLayout'
import { displayFor, type DisplaySettings } from './viewOps'

export interface DerivedActions {
  expression: string
  onEdit: () => void
  onDelete: () => void
}

export interface ViewControlsProps {
  target: BenchViewTarget
  label: string
  packetUnit: string | null
  /** Keyboard alternative to drag-reorder, supplied by the panel that knows the siblings. */
  onMove?: (delta: -1 | 1) => void
  derived?: DerivedActions
}

const menuStyle: React.CSSProperties = {
  position: 'absolute',
  right: 0,
  top: '1.6rem',
  zIndex: 5,
  display: 'grid',
  gap: 4,
  minWidth: 200,
  padding: 8,
  background: 'var(--bg)',
  border: '1px solid var(--line, var(--mut))',
  borderRadius: 6
}

export function ViewControls(props: ViewControlsProps): React.JSX.Element | null {
  const context = useBenchViewContext()
  const [open, setOpen] = useState(false)
  if (!context || (!context.canEdit && !props.derived)) return null
  return (
    <div style={{ position: 'relative', marginLeft: 'auto' }}>
      <button
        type="button"
        className="bench-text-button"
        aria-label={`View options for ${props.label}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        ⋯
      </button>
      {open && (
        <div role="menu" aria-label={`${props.label} view options`} style={menuStyle}>
          {context.canEdit ? (
            <MemberMenu {...props} projectId={context.projectId} close={() => setOpen(false)} />
          ) : (
            <CopyExpression
              expression={props.derived?.expression ?? ''}
              close={() => setOpen(false)}
            />
          )}
        </div>
      )}
    </div>
  )
}

function CopyExpression({
  expression,
  close
}: {
  expression: string
  close: () => void
}): React.JSX.Element {
  return (
    <button
      type="button"
      role="menuitem"
      className="bench-text-button"
      onClick={() => {
        void navigator.clipboard?.writeText(expression).catch(() => undefined)
        close()
      }}
    >
      Copy expression
    </button>
  )
}

function Item({ label, onClick }: { label: string; onClick: () => void }): React.JSX.Element {
  return (
    <button type="button" role="menuitem" className="bench-text-button" onClick={onClick}>
      {label}
    </button>
  )
}

function MemberMenu({
  target,
  label,
  packetUnit,
  onMove,
  derived,
  projectId,
  close
}: ViewControlsProps & { projectId: string; close: () => void }): React.JSX.Element {
  const context = useBenchViewContext()
  const notice = useBenchViewStore((state) => state.projects[projectId]?.notice ?? null)
  const settings = displayFor(context?.view ?? null, target)
  const apply = (patch: BenchViewDisplayPatch): void => {
    void useBenchViewStore
      .getState()
      .setDisplay(projectId, [{ kind: 'set_display', target, patch }])
    close()
  }
  const act: Act = (run) => () => {
    run()
    close()
  }
  return (
    <>
      <Item
        label={settings.pinned ? 'Unpin' : 'Pin'}
        onClick={() => apply({ pinned: settings.pinned ? null : true })}
      />
      <Item label="Hide" onClick={() => apply({ hidden: true })} />
      {onMove && <MoveItems onMove={onMove} act={act} />}
      <UnitPicker label={label} packetUnit={packetUnit} settings={settings} apply={apply} />
      <RangeEditor label={label} settings={settings} apply={apply} />
      <GroupPicker
        label={label}
        settings={settings}
        groups={plotGroups(context?.view ?? null)}
        apply={apply}
      />
      {derived && <DerivedItems derived={derived} act={act} />}
      {notice && <p role="alert">{notice}</p>}
    </>
  )
}

type Act = (run: () => void) => () => void

function MoveItems({
  onMove,
  act
}: {
  onMove: (delta: -1 | 1) => void
  act: Act
}): React.JSX.Element {
  return (
    <>
      <Item label="Move earlier" onClick={act(() => onMove(-1))} />
      <Item label="Move later" onClick={act(() => onMove(1))} />
    </>
  )
}

function DerivedItems({ derived, act }: { derived: DerivedActions; act: Act }): React.JSX.Element {
  return (
    <>
      <Item label="Edit" onClick={act(derived.onEdit)} />
      <Item label="Delete" onClick={act(derived.onDelete)} />
    </>
  )
}

interface PickerProps {
  label: string
  settings: DisplaySettings
  apply: (patch: BenchViewDisplayPatch) => void
}

function UnitPicker({
  label,
  packetUnit,
  settings,
  apply
}: PickerProps & { packetUnit: string | null }): React.JSX.Element | null {
  const options = unitOptions(packetUnit)
  if (options.length < 2) return null
  const current = settings.unit && options.includes(settings.unit) ? settings.unit : packetUnit
  return (
    <label>
      Unit{' '}
      <select
        aria-label={`Unit for ${label}`}
        value={current ?? ''}
        onChange={(event) =>
          apply({ unit: event.target.value === packetUnit ? null : event.target.value })
        }
      >
        {options.map((option) => (
          <option key={option}>{option}</option>
        ))}
      </select>
    </label>
  )
}

function parseLimit(text: string): number | null {
  const value = Number(text)
  return text.trim() &&
    Number.isFinite(value) &&
    Math.abs(value) <= BENCH_VIEW_LIMITS.maxLimitMagnitude
    ? value
    : null
}

function RangeEditor({ label, settings, apply }: PickerProps): React.JSX.Element {
  const [min, setMin] = useState(settings.limits ? String(settings.limits.min) : '')
  const [max, setMax] = useState(settings.limits ? String(settings.limits.max) : '')
  const [error, setError] = useState<string | null>(null)
  function submit(): void {
    const low = parseLimit(min)
    const high = parseLimit(max)
    if (low === null || high === null) return setError('Enter two finite numbers.')
    if (low >= high) return setError('Min must be below max.')
    apply({ limits: { min: low, max: high } })
  }
  return (
    <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
      <legend>Axis range</legend>
      <input
        aria-label={`Axis min for ${label}`}
        inputMode="decimal"
        size={6}
        value={min}
        onChange={(e) => setMin(e.target.value)}
      />
      <input
        aria-label={`Axis max for ${label}`}
        inputMode="decimal"
        size={6}
        value={max}
        onChange={(e) => setMax(e.target.value)}
      />
      <button type="button" className="bench-text-button" onClick={submit}>
        Apply range
      </button>
      <button type="button" className="bench-text-button" onClick={() => apply({ limits: null })}>
        Auto
      </button>
      {error && <p role="alert">{error}</p>}
    </fieldset>
  )
}

const NONE = ''

function GroupPicker({
  label,
  settings,
  groups,
  apply
}: PickerProps & { groups: string[] }): React.JSX.Element {
  const [draft, setDraft] = useState('')
  const name = draft.trim()
  return (
    <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
      <legend>Plot group</legend>
      <select
        aria-label={`Plot group for ${label}`}
        value={settings.plot_group ?? NONE}
        onChange={(event) =>
          apply({ plot_group: event.target.value === NONE ? null : event.target.value })
        }
      >
        <option value={NONE}>None</option>
        {groups.map((group) => (
          <option key={group} value={group}>
            {group}
          </option>
        ))}
      </select>
      <input
        aria-label={`New plot group for ${label}`}
        placeholder="New group…"
        maxLength={BENCH_VIEW_LIMITS.maxGroupChars}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
      <button
        type="button"
        className="bench-text-button"
        disabled={!name}
        onClick={() => apply({ plot_group: name })}
      >
        Create group
      </button>
    </fieldset>
  )
}
