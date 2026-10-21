// SOLUSDEV-317 — the ⌘K command palette (command-palette.md). Presentation and
// keyboard only: items arrive ready-made from PaletteHost, a pick goes back out
// through `onPick` with its rank. Modelled on a combobox + listbox so screen
// readers announce the active result while focus stays in the field.
import { useEffect, useMemo, useRef, useState } from 'react'
import { Icons } from '../../components/ui/icons.constants'
import type { PaletteItem } from './paletteItems'
import {
  buildSections,
  flattenSections,
  type PaletteFilter,
  type PaletteSection
} from './paletteRank'
import './palette.css'

export interface CommandPaletteProps {
  items: readonly PaletteItem[]
  recentKeys: readonly string[]
  /** Projects/teams or the open project's nodes are still loading. */
  loading: boolean
  hasProject: boolean
  onPick: (item: PaletteItem, rank: number, query: string) => void
  onClose: () => void
}

const FILTERS: readonly { id: PaletteFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'page', label: 'Pages' },
  { id: 'project', label: 'Projects' },
  { id: 'team', label: 'Teams' },
  { id: 'node', label: 'Nodes' }
]

type IconName = keyof typeof Icons

const SCREEN_ICONS: Readonly<Record<string, IconName>> = {
  home: 'home',
  workspace: 'graph',
  bench: 'bench',
  sol: 'sol',
  store: 'grid',
  billing: 'card',
  settings: 'gear'
}

function iconFor(item: PaletteItem): IconName {
  switch (item.target.type) {
    case 'screen':
      return SCREEN_ICONS[item.target.screen] ?? 'grid'
    case 'extension':
      return 'diamond'
    case 'project':
      return 'box'
    case 'team':
      return 'team'
    case 'node':
      return 'hex'
  }
}

const optionId = (section: PaletteSection, item: PaletteItem): string =>
  `palette-option-${section.title === 'Recents' ? 'recent-' : ''}${item.key}`

export function CommandPalette(props: CommandPaletteProps): React.JSX.Element {
  const { items, recentKeys, onPick, onClose } = props
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<PaletteFilter>('all')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const sections = useMemo(
    () => buildSections(items, query, filter, recentKeys),
    [items, query, filter, recentKeys]
  )
  const flat = useMemo(() => flattenSections(sections), [sections])
  const ids = useMemo(
    () => sections.flatMap((section) => section.items.map((item) => optionId(section, item))),
    [sections]
  )
  // A recent also appears in its kind's section, so offsets are a running sum — never indexOf.
  const offsets = useMemo(
    () => sections.map((_, i) => sections.slice(0, i).reduce((n, s) => n + s.items.length, 0)),
    [sections]
  )
  // Only keyboard moves scroll the list; a hover must not move rows under the cursor.
  const scrollOnMove = useRef(false)
  const current = flat.length ? Math.min(active, flat.length - 1) : -1

  useRestoreFocus(inputRef)
  useEffect(() => {
    if (!scrollOnMove.current || current < 0) return
    scrollOnMove.current = false
    document.getElementById(ids[current])?.scrollIntoView?.({ block: 'nearest' })
  }, [current, ids])

  const changeFilter = (next: PaletteFilter): void => {
    setFilter(next)
    setActive(0)
  }
  const step = (delta: number): void => {
    if (!flat.length) return
    scrollOnMove.current = true
    setActive((current + delta + flat.length) % flat.length)
  }
  const cycleFilter = (delta: number): void => {
    const at = FILTERS.findIndex((f) => f.id === filter)
    changeFilter(FILTERS[(at + delta + FILTERS.length) % FILTERS.length].id)
  }
  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>): void => {
    const handlers: Record<string, () => void> = {
      ArrowDown: () => step(1),
      ArrowUp: () => step(-1),
      Tab: () => cycleFilter(event.shiftKey ? -1 : 1),
      Enter: () => current >= 0 && onPick(flat[current], current, query),
      Escape: onClose
    }
    const handler = handlers[event.key]
    if (!handler || event.nativeEvent.isComposing) return
    event.preventDefault()
    handler()
  }

  return (
    <div
      className="palette-backdrop modal-backdrop-in"
      data-testid="palette-backdrop"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="palette popover-in" role="dialog" aria-modal="true" aria-label="Search">
        <div className="palette-head">
          <Icons.search size={14} />
          <input
            ref={inputRef}
            className="palette-input"
            role="combobox"
            aria-label="Search Solus"
            aria-expanded="true"
            aria-controls="palette-results"
            aria-autocomplete="list"
            aria-activedescendant={current >= 0 ? ids[current] : undefined}
            placeholder="Search pages, projects, teams, nodes…"
            value={query}
            spellCheck={false}
            onChange={(e) => {
              setQuery(e.target.value)
              setActive(0)
            }}
            onKeyDown={onKeyDown}
          />
          <button
            type="button"
            className="palette-close"
            aria-label="Close search"
            onClick={onClose}
          >
            <Icons.x size={13} />
          </button>
        </div>
        <FilterTabs filter={filter} onChange={changeFilter} />
        {props.loading && (
          <div role="status" className="palette-note">
            Loading…
          </div>
        )}
        <div id="palette-results" role="listbox" aria-label="Results" className="palette-results">
          {sections.map((section, i) => (
            <ResultSection
              key={section.title}
              section={section}
              offset={offsets[i]}
              current={current}
              onHover={setActive}
              onPick={(item, rank) => onPick(item, rank, query)}
            />
          ))}
          {flat.length === 0 && (
            <EmptyResults query={query} filter={filter} hasProject={props.hasProject} />
          )}
        </div>
        <PaletteFooter />
      </div>
    </div>
  )
}

/** Focus the field on open; hand focus back to the opener on close (dialog pattern). */
function useRestoreFocus(inputRef: React.RefObject<HTMLInputElement | null>): void {
  useEffect(() => {
    const opener = document.activeElement
    inputRef.current?.focus()
    return () => {
      // A pick that navigated elsewhere may have removed the opener; then focus stays put.
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus()
    }
  }, [inputRef])
}

function FilterTabs({
  filter,
  onChange
}: {
  filter: PaletteFilter
  onChange: (filter: PaletteFilter) => void
}): React.JSX.Element {
  return (
    <div role="tablist" aria-label="Result type" className="palette-tabs">
      {FILTERS.map((f) => (
        <button
          key={f.id}
          type="button"
          role="tab"
          tabIndex={-1}
          aria-selected={filter === f.id}
          className="palette-tab"
          // Keep focus in the field: a tab click must not steal it.
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => onChange(f.id)}
        >
          {f.label}
        </button>
      ))}
    </div>
  )
}

function ResultSection({
  section,
  offset,
  current,
  onHover,
  onPick
}: {
  section: PaletteSection
  offset: number
  current: number
  onHover: (index: number) => void
  onPick: (item: PaletteItem, rank: number) => void
}): React.JSX.Element {
  return (
    <div role="group" aria-label={section.title}>
      <div className="palette-section">{section.title}</div>
      {section.items.map((item, i) => {
        const rank = offset + i
        const Icon = Icons[iconFor(item)]
        return (
          <div
            key={optionId(section, item)}
            id={optionId(section, item)}
            data-key={item.key}
            role="option"
            aria-selected={rank === current}
            className="palette-option"
            onMouseMove={() => rank !== current && onHover(rank)}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => onPick(item, rank)}
          >
            <span className="palette-option-icon">
              <Icon size={14} />
            </span>
            <span className="palette-option-label">{item.label}</span>
            {item.detail && <span className="palette-option-detail">{item.detail}</span>}
            {rank === current && <span className="palette-option-enter">↵</span>}
          </div>
        )
      })}
    </div>
  )
}

function EmptyResults({
  query,
  filter,
  hasProject
}: {
  query: string
  filter: PaletteFilter
  hasProject: boolean
}): React.JSX.Element {
  const text =
    filter === 'node' && !hasProject
      ? 'Open a project to search its nodes.'
      : query.trim()
        ? `No results for “${query.trim()}”`
        : 'Nothing here yet.'
  return <div className="palette-empty">{text}</div>
}

function PaletteFooter(): React.JSX.Element {
  const hints: readonly [string, string][] = [
    ['Close', 'Esc'],
    ['Navigate', '↑ ↓'],
    ['Change type', 'Tab'],
    ['Open', '↵']
  ]
  return (
    <div className="palette-footer" aria-hidden="true">
      {hints.map(([label, key]) => (
        <span key={label}>
          {label} <kbd>{key}</kbd>
        </span>
      ))}
    </div>
  )
}
