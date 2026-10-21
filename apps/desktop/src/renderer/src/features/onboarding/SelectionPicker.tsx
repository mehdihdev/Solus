// The picker over whatever a connected source can track — repositories, CAD
// documents, anything a future connector offers. Shared by the connect tile and
// the "edit selection" modal so both stay identical.
//
// Nothing here knows what an item IS: `mode` comes from the connector's declared
// selection, and the item's own `name`/`subtitle` are the only copy shown.
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'
import type { SelectableItem } from '../../lib/api/resources'
import type { PickerSection } from './teamRepoSection'
import { MultiSelectPicker, useRefreshedItems, type PickerVariant } from './MultiSelectPicker'

export const PICKER_FIELD_STYLE = {
  width: '100%',
  background: 'var(--sur)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '7px 9px',
  fontSize: 11.5,
  fontFamily: 'var(--font-mono)',
  outline: 'none'
} as const

const SUB = { fontFamily: 'var(--font-mono)', fontSize: 10.5 } as const

/** Search + "Load more" for the team section's repository listing. */
export interface PickerPaging {
  query: string
  onSearch: (query: string) => void
  /** Repositories currently listed, and the server's total when it reports one. */
  shown: number
  total: number | null
  hasMore: boolean
  /** A search or page fetch is in flight. */
  busy: boolean
  /** Mode-aware sentence when the last search/page fetch failed. */
  error: string | null
  onLoadMore: () => void
}

export interface SelectionPickerProps {
  items: readonly SelectableItem[]
  mode?: 'single' | 'multi'
  /** Report the chosen items. An empty array is a valid multi-select answer. */
  onSelect?: (items: SelectableItem[] | null) => void
  /** Items already tracked, so an edit starts from the current selection. */
  initial?: readonly string[]
  /** The connector's noun ("document") for multi-select copy. */
  label?: string
  /** Multi-select: first pick (`connect`) or changing a selection (`edit`). */
  variant?: PickerVariant
  /** Multi-select edit: leave without saving. */
  onCancel?: () => void
  onRefresh?: () => Promise<SelectableItem[]>
  refreshLabel?: string
  disabled?: boolean
  /** SOLUSDEV-216: headed groups of one-click choices (team repos, then your
   *  account). Present, they replace `items`; each click reports one item. */
  sections?: readonly PickerSection[]
  /** Search + paging for the FIRST section (the team's repositories). */
  paging?: PickerPaging
}

function PagingSearch({ paging }: { paging: PickerPaging }): React.JSX.Element {
  return (
    <input
      type="search"
      aria-label="Search repositories"
      placeholder="Search repositories"
      value={paging.query}
      onChange={(e) => paging.onSearch(e.target.value)}
      style={{ ...PICKER_FIELD_STYLE, marginTop: 6 }}
    />
  )
}

function PagingFooter({ paging }: { paging: PickerPaging }): React.JSX.Element {
  const count =
    paging.hasMore && paging.total !== null
      ? `Showing ${paging.shown} of ${paging.total}`
      : `Showing ${paging.shown}`
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6 }}>
      {paging.busy && <Spinner size={11} />}
      {paging.error && (
        <div role="alert" style={{ fontSize: 11.5, color: 'var(--err)' }}>
          {paging.error}
        </div>
      )}
      {paging.hasMore && (
        <>
          <span data-testid="picker-showing" style={{ ...SUB, color: 'var(--mut)' }}>
            {count}
          </span>
          <Button kind="ghost" size="sm" disabled={paging.busy} onClick={paging.onLoadMore}>
            Load more
          </Button>
        </>
      )}
    </div>
  )
}

/** Headed groups of one-click choices. */
function SectionedPicker({
  sections = [],
  onSelect,
  paging
}: SelectionPickerProps): React.JSX.Element {
  return (
    <div
      onClick={(e) => e.stopPropagation()}
      style={{ display: 'grid', gap: 10, textAlign: 'left' }}
    >
      {sections.map((section, index) => (
        <div key={section.header} role="group" aria-label={section.header}>
          <div
            style={{
              ...SUB,
              color: 'var(--mut)',
              letterSpacing: 0.4,
              textTransform: 'uppercase'
            }}
          >
            {section.header}
          </div>
          {index === 0 && paging && <PagingSearch paging={paging} />}
          {section.notice && (
            <div role="status" style={{ fontSize: 11.5, marginTop: 4 }}>
              {section.notice}
            </div>
          )}
          <div style={{ display: 'grid', gap: 2, marginTop: 4, maxHeight: 148, overflowY: 'auto' }}>
            {section.items.map((item) => (
              <button
                key={item.id}
                type="button"
                className="interactive"
                onClick={() => onSelect?.([item])}
                style={{
                  display: 'flex',
                  gap: 8,
                  justifyContent: 'space-between',
                  background: 'none',
                  border: 'none',
                  color: 'var(--tx)',
                  padding: '4px 0',
                  fontSize: 11.5,
                  textAlign: 'left',
                  cursor: 'pointer'
                }}
              >
                <span>{item.name}</span>
                {item.subtitle && (
                  <span style={{ ...SUB, color: 'var(--mut)' }}>{item.subtitle}</span>
                )}
              </button>
            ))}
          </div>
          {index === 0 && paging && <PagingFooter paging={paging} />}
        </div>
      ))}
    </div>
  )
}

/** Single-select: one item, chosen from a dropdown. */
function SinglePicker({ items, onSelect }: SelectionPickerProps): React.JSX.Element {
  return (
    <select
      aria-label="Choose an item to track"
      defaultValue=""
      onChange={(e) => {
        const item = items.find((i) => i.id === e.target.value)
        if (item) onSelect?.([item])
      }}
      onClick={(e) => e.stopPropagation()}
      style={{ ...PICKER_FIELD_STYLE, marginTop: 8 }}
    >
      <option value="" disabled>
        Select one…
      </option>
      {items.map((item) => (
        <option key={item.id} value={item.id}>
          {item.name}
        </option>
      ))}
    </select>
  )
}

function PickerBody(props: SelectionPickerProps): React.JSX.Element {
  if (props.sections) return <SectionedPicker {...props} />
  return <SinglePicker {...props} />
}

export function SelectionPicker(props: SelectionPickerProps): React.JSX.Element {
  if (!props.sections && props.mode === 'multi') {
    return (
      <MultiSelectPicker
        items={props.items}
        label={props.label ?? 'item'}
        variant={props.variant ?? 'connect'}
        initial={props.initial ?? []}
        onSelect={props.onSelect}
        onCancel={props.onCancel}
        onRefresh={props.onRefresh}
        disabled={props.disabled}
      />
    )
  }
  return <SingleOrSections {...props} />
}

function SingleOrSections(props: SelectionPickerProps): React.JSX.Element {
  const listing = useRefreshedItems(props)
  const pickerProps = { ...props, items: listing.items }
  return (
    <>
      <fieldset
        disabled={listing.busy || props.disabled}
        style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}
      >
        <PickerBody {...pickerProps} />
        {props.onRefresh && (
          <Button kind="ghost" size="sm" onClick={() => void listing.refresh()}>
            {listing.busy ? 'Refreshing…' : (props.refreshLabel ?? 'Refresh list')}
          </Button>
        )}
      </fieldset>
      {listing.error && <div role="alert">{listing.error}</div>}
      {!props.sections && !listing.busy && listing.items.length === 0 && (
        <div role="status">No items found.</div>
      )}
    </>
  )
}
