// SOLUSDEV-317: the one picker of the GitHub assignment, used from both sides
// (a teammate for an org row; an org member for a teammate). A popover listbox
// with roving focus: arrows / Home / End move between enabled options, Enter or
// Space picks, Escape (or a click away) closes and returns focus to the trigger.
// Past 8 options it gains a search box. Labels are text, never HTML.
// The popover is portalled to document.body at a fixed position: every roster
// row animates in (`home-row-in`, a transform), so each row is its own stacking
// context and an in-row popover would paint under the next row's buttons.
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Button } from '../../components/ui/Button'
import type { PickerOption } from './githubOrgMembersView'

/** More options than this and the picker gains a search filter. */
export const PICKER_SEARCH_THRESHOLD = 8

export interface AssignPickerProps {
  /** Trigger text ("Assign", "Change", "Pick GitHub account"). */
  label: string
  /** The listbox's accessible name. */
  listLabel: string
  options: readonly PickerOption[]
  emptyText: string
  onPick: (id: string) => void
  disabled?: boolean
  /** Opens the picker whenever this changes to a new non-zero value. */
  openRequest?: number
}

const POPOVER_WIDTH = 260
const POPOVER_MAX_HEIGHT = 280
const POPOVER_GAP = 4
const VIEWPORT_MARGIN = 8

const POPOVER: React.CSSProperties = {
  position: 'fixed',
  zIndex: 80,
  width: POPOVER_WIDTH,
  maxHeight: POPOVER_MAX_HEIGHT,
  overflowY: 'auto',
  background: 'var(--sur)',
  border: '1px solid var(--bd)',
  borderRadius: 4,
  boxShadow: '0 10px 30px rgba(0,0,0,0.35)',
  padding: 4
}

const SEARCH: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  marginBottom: 4,
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '6px 8px',
  fontSize: 12,
  fontFamily: 'var(--font-ui)',
  outline: 'none'
}

export type PopoverPlacement = { left: number } & ({ top: number } | { bottom: number })

/** Where the fixed popover goes: right-aligned under the trigger, flipped above
 *  it when the viewport has no room below, never off the left edge. */
export function popoverPlacement(
  rect: Pick<DOMRect, 'top' | 'bottom' | 'right'>,
  viewport: { width: number; height: number }
): PopoverPlacement {
  const left = Math.max(VIEWPORT_MARGIN, rect.right - POPOVER_WIDTH)
  const below = rect.bottom + POPOVER_GAP
  const fitsBelow = below + POPOVER_MAX_HEIGHT <= viewport.height - VIEWPORT_MARGIN
  if (fitsBelow || rect.top < viewport.height - rect.bottom) return { left, top: below }
  return { left, bottom: viewport.height - rect.top + POPOVER_GAP }
}

const visible = (options: readonly PickerOption[], query: string): PickerOption[] => {
  const q = query.trim().toLowerCase()
  if (!q) return [...options]
  return options.filter((o) => `${o.label} ${o.detail}`.toLowerCase().includes(q))
}

/** The next enabled index from `from` in `step` direction, or `from`. */
function nextEnabled(options: readonly PickerOption[], from: number, step: 1 | -1): number {
  for (let i = from + step; i >= 0 && i < options.length; i += step) {
    if (!options[i].disabled) return i
  }
  return from
}

export function AssignPicker(props: AssignPickerProps): React.JSX.Element {
  const { label, disabled = false, openRequest = 0 } = props
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLSpanElement>(null)
  const popRef = useRef<HTMLDivElement>(null)
  const [place, setPlace] = useState<PopoverPlacement | null>(null)
  const listId = useId()
  useEffect(() => {
    if (openRequest) setOpen(true)
  }, [openRequest])
  useLayoutEffect(() => {
    const trigger = rootRef.current?.querySelector('button[aria-haspopup]')
    if (!open || !trigger) return setPlace(null)
    const viewport = { width: window.innerWidth, height: window.innerHeight }
    setPlace(popoverPlacement(trigger.getBoundingClientRect(), viewport))
  }, [open])
  useClickAway([rootRef, popRef], open, () => setOpen(false))
  // A fixed popover would drift from its trigger: close on page scroll / resize.
  useCloseOnMove(popRef, open, () => setOpen(false))
  const close = (): void => {
    setOpen(false)
    rootRef.current?.querySelector<HTMLButtonElement>('button[aria-haspopup]')?.focus()
  }
  return (
    <span ref={rootRef} style={{ position: 'relative', display: 'inline-flex' }}>
      <Button
        kind="soft"
        size="sm"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        onClick={() => setOpen((v) => !v)}
      >
        {label}
      </Button>
      {open &&
        place &&
        createPortal(
          <PickerPopover
            {...props}
            listId={listId}
            popRef={popRef}
            place={place}
            onClose={close}
            onDismiss={() => setOpen(false)}
          />,
          document.body
        )}
    </span>
  )
}

type ElementRef = React.RefObject<HTMLElement | null>

const inside = (refs: readonly ElementRef[], target: EventTarget | null): boolean =>
  target instanceof Node && refs.some((r) => r.current?.contains(target))

/** A press outside the trigger AND the portalled popover closes it. */
function useClickAway(refs: readonly ElementRef[], active: boolean, onAway: () => void): void {
  const latest = useRef({ refs, onAway })
  latest.current = { refs, onAway }
  useEffect(() => {
    if (!active) return
    const onDown = (event: MouseEvent): void => {
      if (!inside(latest.current.refs, event.target)) latest.current.onAway()
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [active])
}

/** Page scroll (not the popover's own list) or a resize closes it. */
function useCloseOnMove(popRef: ElementRef, active: boolean, onMove: () => void): void {
  const latest = useRef(onMove)
  latest.current = onMove
  useEffect(() => {
    if (!active) return
    const onScroll = (event: Event): void => {
      if (!inside([popRef], event.target)) latest.current()
    }
    const onResize = (): void => latest.current()
    document.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onResize)
    return () => {
      document.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onResize)
    }
  }, [popRef, active])
}

function PickerPopover({
  listLabel,
  options,
  emptyText,
  onPick,
  listId,
  popRef,
  place,
  onClose,
  onDismiss
}: AssignPickerProps & {
  listId: string
  popRef: React.RefObject<HTMLDivElement | null>
  place: PopoverPlacement
  onClose: () => void
  /** Tab moved focus away: close without pulling focus back. */
  onDismiss: () => void
}): React.JSX.Element {
  const [query, setQuery] = useState('')
  const shown = visible(options, query)
  const searchable = options.length > PICKER_SEARCH_THRESHOLD
  const [active, setActive] = useState(() => nextEnabled(shown, -1, 1))
  const listRef = useRef<HTMLUListElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const focusOption = (i: number): void => {
    setActive(i)
    listRef.current?.querySelectorAll<HTMLElement>('[role="option"]')[i]?.focus()
  }
  useOpenFocus(() => {
    if (searchable) searchRef.current?.focus()
    else if (active >= 0) focusOption(active)
    // Nothing pickable: hold focus in the popover so Escape still closes it.
    else listRef.current?.focus()
  })
  const pick = (option: PickerOption | undefined): void => {
    if (!option || option.disabled) return
    onPick(option.id)
    onClose()
  }
  const onKeyDown = keyHandler({
    shown,
    active,
    isSearch: (target) => target === searchRef.current,
    focusOption,
    pick,
    onClose
  })
  return (
    <div
      ref={popRef}
      className="popover-in"
      style={{ ...POPOVER, ...place }}
      onKeyDown={onKeyDown}
      onBlur={(event) => leftPopover(event) && onDismiss()}
    >
      {searchable && (
        <PickerSearch
          inputRef={searchRef}
          label={`Search ${listLabel}`}
          value={query}
          onChange={(value) => {
            setQuery(value)
            setActive(-1)
          }}
        />
      )}
      <PickerList
        listRef={listRef}
        listId={listId}
        listLabel={listLabel}
        shown={shown}
        active={active}
        emptyText={emptyText}
        onPick={pick}
      />
    </div>
  )
}

/** Runs once, on open. */
function useOpenFocus(focus: () => void): void {
  const once = useRef(focus)
  useEffect(() => once.current(), [])
}

/** Focus moved to something outside the popover (Tab away). */
const leftPopover = (event: React.FocusEvent<HTMLElement>): boolean =>
  event.relatedTarget instanceof Node && !event.currentTarget.contains(event.relatedTarget)

function PickerList({
  listRef,
  listId,
  listLabel,
  shown,
  active,
  emptyText,
  onPick
}: {
  listRef: React.RefObject<HTMLUListElement | null>
  listId: string
  listLabel: string
  shown: readonly PickerOption[]
  active: number
  emptyText: string
  onPick: (option: PickerOption) => void
}): React.JSX.Element {
  return (
    <>
      <ul
        ref={listRef}
        id={listId}
        role="listbox"
        aria-label={listLabel}
        tabIndex={-1}
        style={{ listStyle: 'none', margin: 0, padding: 0 }}
      >
        {shown.map((o, i) => (
          <PickerRow key={o.id} option={o} focusable={i === active} onPick={() => onPick(o)} />
        ))}
      </ul>
      {shown.length === 0 && (
        <div style={{ padding: '8px 10px', fontSize: 11.5, color: 'var(--mut)' }}>{emptyText}</div>
      )}
    </>
  )
}

function PickerSearch({
  inputRef,
  label,
  value,
  onChange
}: {
  inputRef: React.RefObject<HTMLInputElement | null>
  label: string
  value: string
  onChange: (value: string) => void
}): React.JSX.Element {
  return (
    <input
      ref={inputRef}
      type="search"
      aria-label={label}
      placeholder="Search…"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={SEARCH}
    />
  )
}

interface KeyContext {
  shown: readonly PickerOption[]
  active: number
  isSearch: (target: EventTarget) => boolean
  focusOption: (index: number) => void
  pick: (option: PickerOption | undefined) => void
  onClose: () => void
}

/** Escape closes; arrows / Home / End move; Enter or Space (outside search) picks. */
function keyHandler(ctx: KeyContext): (event: React.KeyboardEvent) => void {
  return (event) => {
    const move = keyMove(event.key, ctx.shown, ctx.active)
    // Tab, like Escape, closes back onto the trigger: the portal sits at the end
    // of <body>, so letting Tab run on would leave the page's focus order.
    if (event.key === 'Escape' || event.key === 'Tab') ctx.onClose()
    else if (move !== null) ctx.focusOption(move)
    else if ((event.key === 'Enter' || event.key === ' ') && !ctx.isSearch(event.target)) {
      ctx.pick(ctx.shown[ctx.active])
    } else return
    event.preventDefault()
    event.stopPropagation()
  }
}

/** Arrow / Home / End: the index to focus, or null for any other key. */
function keyMove(key: string, options: readonly PickerOption[], active: number): number | null {
  switch (key) {
    case 'ArrowDown':
      return nextEnabled(options, active, 1)
    case 'ArrowUp':
      return active <= 0 ? active : nextEnabled(options, active, -1)
    case 'Home':
      return nextEnabled(options, -1, 1)
    case 'End':
      return nextEnabled(options, options.length, -1)
    default:
      return null
  }
}

function PickerRow({
  option,
  focusable,
  onPick
}: {
  option: PickerOption
  focusable: boolean
  onPick: () => void
}): React.JSX.Element {
  return (
    <li
      role="option"
      aria-selected={false}
      aria-disabled={option.disabled}
      tabIndex={focusable ? 0 : -1}
      className={option.disabled ? undefined : 'interactive'}
      onClick={onPick}
      style={{
        padding: '7px 10px',
        borderRadius: 3,
        cursor: option.disabled ? 'not-allowed' : 'pointer',
        opacity: option.disabled ? 0.55 : 1,
        outline: 'none',
        background: focusable ? 'var(--sur2)' : 'transparent'
      }}
    >
      <div style={{ fontSize: 12.5, wordBreak: 'break-all' }}>{option.label}</div>
      <div style={{ fontSize: 10.5, color: 'var(--mut)', wordBreak: 'break-all' }}>
        {option.detail}
      </div>
    </li>
  )
}
