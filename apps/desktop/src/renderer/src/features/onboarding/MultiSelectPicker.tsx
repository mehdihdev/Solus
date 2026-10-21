// Multi-select over whatever a source can track (Onshape documents today). Two
// variants share one list: CONNECT is the first pick (Track N / Skip for now),
// EDIT changes an existing selection (tracked pinned on top, Adding/Removing
// marks, a diff, Save / Cancel). Item-agnostic: the connector's noun and the
// items' own name/subtitle/modified_at are the only copy shown.
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { Button } from '../../components/ui/Button'
import { Icons } from '../../components/ui/icons.constants'
import { Mono } from '../../components/ui/Mono'
import type { SelectableItem } from '../../lib/api/resources'
import { relativeTime } from '../../lib/relativeTime'
import {
  confirmLabel,
  countOf,
  matches,
  orderItems,
  selectionDiff,
  toggled,
  toggledAll
} from './pickerModel'
import { plural } from './selectionConfigureStep'

export type PickerVariant = 'connect' | 'edit'

export interface MultiSelectPickerProps {
  items: readonly SelectableItem[]
  /** The connector's noun ("document"). */
  label: string
  variant: PickerVariant
  initial: readonly string[]
  onSelect?: (items: SelectableItem[] | null) => void
  onCancel?: () => void
  onRefresh?: () => Promise<SelectableItem[]>
  disabled?: boolean
}

const MONO: CSSProperties = { fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)' }
const ROW: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  minHeight: 38,
  padding: '0 12px',
  borderTop: '1px solid var(--bd)'
}
const BADGE: CSSProperties = {
  ...MONO,
  fontSize: 10,
  borderRadius: 3,
  padding: '1px 6px',
  textTransform: 'uppercase',
  border: '1px solid currentColor'
}
const LINK: CSSProperties = {
  border: 0,
  background: 'none',
  padding: 0,
  color: 'var(--mut)',
  fontSize: 11.5,
  textDecoration: 'underline',
  cursor: 'pointer'
}

/** The listing, refreshed on demand. A late answer for a picker that has since
 *  closed or changed source is dropped; a failure keeps the old listing. */
export interface RefreshedItems {
  items: readonly SelectableItem[]
  busy: boolean
  error: string | null
  refresh: () => Promise<void>
}

export function useRefreshedItems(props: {
  items: readonly SelectableItem[]
  onRefresh?: () => Promise<SelectableItem[]>
  disabled?: boolean
}): RefreshedItems {
  const [items, setItems] = useState(props.items)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const generation = useRef(0)
  const pending = useRef(false)
  useEffect(() => {
    setItems(props.items)
    setBusy(false)
    setError(null)
    pending.current = false
    generation.current += 1
    return () => {
      generation.current += 1
    }
  }, [props.items])
  const refresh = async (): Promise<void> => {
    if (!props.onRefresh || pending.current || props.disabled) return
    const current = generation.current
    pending.current = true
    setBusy(true)
    setError(null)
    try {
      const found = await props.onRefresh()
      if (current === generation.current) setItems(found)
    } catch {
      if (current === generation.current)
        setError("Couldn't refresh the list. Showing the last one; your picks are kept.")
    } finally {
      if (current === generation.current) {
        pending.current = false
        setBusy(false)
      }
    }
  }
  return { items, busy, error, refresh }
}

function RefreshIcon(): React.JSX.Element {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden>
      <path d="M20 11a8 8 0 1 0-2.3 5.7" strokeWidth="2" strokeLinecap="round" />
      <path d="M20 4v7h-7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Toolbar(props: {
  query: string
  onQuery: (q: string) => void
  label: string
  busy: boolean
  onRefresh?: () => void
}): React.JSX.Element {
  const noun = plural(props.label)
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      <label style={{ flex: 1, position: 'relative', display: 'flex', alignItems: 'center' }}>
        <span style={{ position: 'absolute', left: 9, color: 'var(--mut)', display: 'flex' }}>
          <Icons.search size={12} />
        </span>
        <input
          type="search"
          aria-label={`Search ${noun}`}
          placeholder={`Search ${noun}`}
          value={props.query}
          onChange={(e) => props.onQuery(e.target.value)}
          style={{
            width: '100%',
            boxSizing: 'border-box',
            height: 32,
            padding: '0 10px 0 28px',
            background: 'var(--bg)',
            color: 'var(--tx)',
            border: '1px solid var(--bd)',
            borderRadius: 3,
            fontFamily: 'var(--font-ui)',
            fontSize: 12,
            outline: 'none'
          }}
        />
      </label>
      {props.onRefresh && (
        <button
          type="button"
          className="interactive"
          aria-label={`${props.busy ? 'Refreshing' : 'Refresh'} ${noun}`}
          title={`Refresh ${noun}`}
          onClick={props.onRefresh}
          style={{
            width: 32,
            height: 32,
            borderRadius: 3,
            border: '1px solid var(--bd)',
            background: 'transparent',
            color: 'var(--mut)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer'
          }}
        >
          <RefreshIcon />
        </button>
      )}
    </div>
  )
}

type Mark = 'adding' | 'removing' | null

function ItemRow(props: {
  item: SelectableItem
  checked: boolean
  mark: Mark
  onToggle: () => void
}): React.JSX.Element {
  const { item, checked, mark } = props
  const edited = item.modified_at ? relativeTime(item.modified_at) : ''
  return (
    <li style={{ ...ROW, background: checked ? 'var(--sur2)' : 'transparent' }}>
      <label style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
        <input
          type="checkbox"
          aria-label={item.name}
          checked={checked}
          onChange={props.onToggle}
          style={{ accentColor: 'var(--acc)', margin: 0 }}
        />
        <span
          title={item.name}
          style={{
            flex: 1,
            minWidth: 0,
            fontSize: 12.5,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            color: mark === 'removing' ? 'var(--mut)' : 'var(--tx)',
            textDecoration: mark === 'removing' ? 'line-through' : 'none'
          }}
        >
          {item.name}
        </span>
      </label>
      {mark === 'adding' && <span style={{ ...BADGE, color: 'var(--ok)' }}>Adding</span>}
      {mark === 'removing' && (
        <>
          <span style={{ ...BADGE, color: 'var(--err)' }}>Removing</span>
          <button
            type="button"
            aria-label={`Undo removing ${item.name}`}
            onClick={props.onToggle}
            style={LINK}
          >
            Undo
          </button>
        </>
      )}
      {item.subtitle && (
        <span style={{ ...MONO, maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {item.subtitle}
        </span>
      )}
      {edited && <span style={{ ...MONO, width: 64, textAlign: 'right' }}>{edited}</span>}
    </li>
  )
}

function Rows(props: {
  items: readonly SelectableItem[]
  chosen: readonly string[]
  initial: readonly string[]
  variant: PickerVariant
  onToggle: (id: string) => void
}): React.JSX.Element {
  const mark = (id: string): Mark => {
    if (props.variant !== 'edit') return null
    const was = props.initial.includes(id)
    const is = props.chosen.includes(id)
    if (was && !is) return 'removing'
    if (!was && is) return 'adding'
    return null
  }
  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {props.items.map((item) => (
        <ItemRow
          key={item.id}
          item={item}
          checked={props.chosen.includes(item.id)}
          mark={mark(item.id)}
          onToggle={() => props.onToggle(item.id)}
        />
      ))}
    </ul>
  )
}

function Group(props: { title: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <div role="group" aria-label={props.title}>
      <div style={{ padding: '10px 12px 6px' }}>
        <Mono size={10}>{props.title}</Mono>
      </div>
      {props.children}
    </div>
  )
}

function SelectAllBar(props: {
  shown: readonly string[]
  chosen: readonly string[]
  searching: boolean
  hiddenChosen: number
  onToggleAll: () => void
}): React.JSX.Element {
  const n = props.shown.length
  const all = n > 0 && props.shown.every((id) => props.chosen.includes(id))
  const text = props.searching ? `Select ${n} matching` : `Select all ${n} shown`
  return (
    <div
      style={{
        ...MONO,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 12px',
        background: 'var(--bg)'
      }}
    >
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, cursor: 'pointer' }}>
        <input
          type="checkbox"
          aria-label={text}
          checked={all}
          disabled={n === 0}
          onChange={props.onToggleAll}
          style={{ accentColor: 'var(--acc)', margin: 0 }}
        />
        <span style={{ textTransform: 'uppercase' }}>{text}</span>
      </label>
      {props.hiddenChosen > 0 && (
        <span style={{ color: 'var(--acc)' }}>{props.hiddenChosen} selected not shown</span>
      )}
    </div>
  )
}

function ConnectFooter(props: {
  count: number
  label: string
  onClear: () => void
  onSkip: () => void
  onTrack: () => void
}): React.JSX.Element {
  const { count, label } = props
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ flex: 1, minWidth: 0, display: 'grid', gap: 2 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12 }}>
          <span style={{ fontWeight: 600 }}>
            {count === 0 ? 'Nothing selected' : `${countOf(count, label)} selected`}
          </span>
          {count > 0 && (
            <button type="button" onClick={props.onClear} style={LINK}>
              Clear
            </button>
          )}
        </div>
        <span style={MONO}>
          {count === 0
            ? 'Pick at least one, or skip and choose later'
            : `Only these ${plural(label)} are read`}
        </span>
      </div>
      <Button kind="ghost" size="sm" onClick={props.onSkip}>
        Skip for now
      </Button>
      <Button kind="primary" size="sm" disabled={count === 0} onClick={props.onTrack}>
        {confirmLabel(count, label)}
      </Button>
    </div>
  )
}

function EditFooter(props: {
  added: number
  removed: number
  total: number
  label: string
  onCancel?: () => void
  onSave: () => void
}): React.JSX.Element {
  const changed = props.added + props.removed > 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ ...MONO, fontSize: 11, flex: 1, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {changed ? (
          <>
            {props.added > 0 && <span style={{ color: 'var(--ok)' }}>+{props.added} added</span>}
            {props.removed > 0 && (
              <span style={{ color: 'var(--err)' }}>−{props.removed} removed</span>
            )}
            <span>{countOf(props.total, props.label)} tracked after save</span>
          </>
        ) : (
          <span>No changes yet</span>
        )}
      </div>
      <Button kind="ghost" size="sm" onClick={props.onCancel}>
        Cancel
      </Button>
      <Button kind="primary" size="sm" disabled={!changed} onClick={props.onSave}>
        Save changes
      </Button>
    </div>
  )
}

function RemovalNote(props: { names: string[]; label: string }): React.JSX.Element {
  const subject =
    props.names.length === 1 ? props.names[0] : `${props.names.length} ${plural(props.label)}`
  return (
    <div
      role="note"
      style={{
        padding: '9px 11px',
        border: '1px solid var(--warn)',
        borderRadius: 3,
        fontSize: 11.5,
        lineHeight: 1.5,
        display: 'flex',
        gap: 8
      }}
    >
      <span style={{ color: 'var(--warn)', display: 'flex' }}>
        <Icons.warn size={13} />
      </span>
      <span>
        Removing <strong>{subject}</strong> deletes {props.names.length === 1 ? 'its' : 'their'}{' '}
        entities and links from the graph on the next sync. Nothing changes in the source, and
        adding it back re-imports it.
      </span>
    </div>
  )
}

const LIST_BOX: CSSProperties = {
  border: '1px solid var(--bd)',
  borderRadius: 3,
  maxHeight: 300,
  overflowY: 'auto'
}

/** Everything the picker derives from the listing, the picks and the search. */
function usePickerState(props: MultiSelectPickerProps) {
  const listing = useRefreshedItems(props)
  // Snapshot what was tracked when the picker opened: a parent re-render with
  // a refetched source must not shift the Adding/Removing marks under the user.
  const [initial] = useState(props.initial)
  const [chosen, setChosen] = useState<readonly string[]>(initial)
  const [query, setQuery] = useState('')
  const shown = matches(orderItems(listing.items), query)
  const shownIds = shown.map((item) => item.id)
  const listed = new Set(listing.items.map((item) => item.id))
  const picked = listing.items.filter((item) => chosen.includes(item.id))
  // Only ids still in the listing count as tracked: one deleted at the source
  // can neither be shown nor kept.
  const diff = selectionDiff(
    initial.filter((id) => listed.has(id)),
    picked.map((item) => item.id)
  )
  return {
    listing,
    initial,
    chosen,
    setChosen,
    query,
    setQuery,
    shown,
    shownIds,
    picked,
    diff,
    hiddenChosen: picked.filter((item) => !shownIds.includes(item.id)).length,
    removedNames: listing.items.filter((i) => diff.removed.includes(i.id)).map((i) => i.name),
    toggle: (id: string): void => setChosen((prev) => toggled(prev, id))
  }
}

type PickerState = ReturnType<typeof usePickerState>

function EditGroups({
  state,
  initial,
  noun
}: {
  state: PickerState
  initial: readonly string[]
  noun: string
}): React.JSX.Element {
  const tracked = state.shown.filter((item) => initial.includes(item.id))
  const others = state.shown.filter((item) => !initial.includes(item.id))
  const rows = (items: SelectableItem[]): React.JSX.Element => (
    <Rows
      items={items}
      chosen={state.chosen}
      initial={initial}
      variant="edit"
      onToggle={state.toggle}
    />
  )
  return (
    <>
      <Group title={`Tracked now · ${tracked.length}`}>{rows(tracked)}</Group>
      <Group title={`Other ${noun} · ${others.length}`}>{rows(others)}</Group>
    </>
  )
}

function ListBody({
  state,
  variant,
  initial,
  noun
}: {
  state: PickerState
  variant: PickerVariant
  initial: readonly string[]
  noun: string
}): React.JSX.Element {
  if (!state.listing.busy && state.listing.items.length === 0) {
    return (
      <div role="status" style={{ fontSize: 12, color: 'var(--mut)', padding: '16px 0' }}>
        No {noun} found for this account. Create or share one at the source, then refresh.
      </div>
    )
  }
  return (
    <div style={LIST_BOX}>
      {variant === 'edit' ? (
        <EditGroups state={state} initial={initial} noun={noun} />
      ) : (
        <>
          <SelectAllBar
            shown={state.shownIds}
            chosen={state.chosen}
            searching={state.query.trim() !== ''}
            hiddenChosen={state.hiddenChosen}
            onToggleAll={() => state.setChosen((prev) => toggledAll(prev, state.shownIds))}
          />
          <Rows
            items={state.shown}
            chosen={state.chosen}
            initial={initial}
            variant={variant}
            onToggle={state.toggle}
          />
        </>
      )}
      {state.shown.length === 0 && (
        <div
          style={{ padding: '24px 12px', textAlign: 'center', fontSize: 12, color: 'var(--mut)' }}
        >
          No {noun} match “{state.query.trim()}”.
        </div>
      )}
    </div>
  )
}

function Footer({
  state,
  props
}: {
  state: PickerState
  props: MultiSelectPickerProps
}): React.JSX.Element {
  if (props.variant === 'edit') {
    return (
      <EditFooter
        added={state.diff.added.length}
        removed={state.diff.removed.length}
        total={state.picked.length}
        label={props.label}
        onCancel={props.onCancel}
        onSave={() => props.onSelect?.(state.picked)}
      />
    )
  }
  return (
    <ConnectFooter
      count={state.picked.length}
      label={props.label}
      onClear={() => state.setChosen([])}
      onSkip={() => props.onSelect?.([])}
      onTrack={() => props.onSelect?.(state.picked)}
    />
  )
}

export function MultiSelectPicker(props: MultiSelectPickerProps): React.JSX.Element {
  const state = usePickerState(props)
  const noun = plural(props.label)
  const { listing } = state
  return (
    <div onClick={(e) => e.stopPropagation()} style={{ textAlign: 'left' }}>
      <fieldset
        disabled={listing.busy || props.disabled}
        style={{ border: 0, padding: 0, margin: 0, minWidth: 0, display: 'grid', gap: 10 }}
      >
        <Toolbar
          query={state.query}
          onQuery={state.setQuery}
          label={props.label}
          busy={listing.busy}
          onRefresh={props.onRefresh ? () => void listing.refresh() : undefined}
        />
        {listing.error && (
          <div role="alert" style={{ fontSize: 11.5, color: 'var(--err)' }}>
            {listing.error}
          </div>
        )}
        <ListBody state={state} variant={props.variant} initial={state.initial} noun={noun} />
        {props.variant === 'edit' && state.removedNames.length > 0 && (
          <RemovalNote names={state.removedNames} label={props.label} />
        )}
        <Footer state={state} props={props} />
      </fieldset>
    </div>
  )
}
