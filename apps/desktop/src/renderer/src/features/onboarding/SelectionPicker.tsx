// The picker over whatever a connected source can track — repositories, CAD
// documents, anything a future connector offers. Shared by the connect tile and
// the "edit selection" modal so both stay identical.
//
// Nothing here knows what an item IS: `mode` comes from the connector's declared
// selection, and the item's own `name`/`subtitle` are the only copy shown.
import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import type { SelectableItem } from '../../lib/api/resources'
import type { PickerSection } from './teamRepoSection'

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

export interface SelectionPickerProps {
  items: readonly SelectableItem[]
  mode?: 'single' | 'multi'
  /** Report the chosen items. An empty array is a valid multi-select answer. */
  onSelect?: (items: SelectableItem[] | null) => void
  /** Items already tracked, so an edit starts from the current selection. */
  initial?: readonly string[]
  onRefresh?: () => Promise<SelectableItem[]>
  refreshLabel?: string
  disabled?: boolean
  /** SOLUSDEV-216: headed groups of one-click choices (team repos, then your
   *  account). Present, they replace `items`; each click reports one item. */
  sections?: readonly PickerSection[]
}

/** Headed groups of one-click choices. */
function SectionedPicker({ sections = [], onSelect }: SelectionPickerProps): React.JSX.Element {
  return (
    <div
      onClick={(e) => e.stopPropagation()}
      style={{ display: 'grid', gap: 10, textAlign: 'left' }}
    >
      {sections.map((section) => (
        <div key={section.header} role="group" aria-label={section.header}>
          <div style={{ ...SUB, color: 'var(--mut)', letterSpacing: 0.4 }}>{section.header}</div>
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

/** Multi-select: any number of items, confirmed together. Selecting none is a
 *  valid answer — the source stays connected and simply tracks nothing. */
function MultiPicker({ items, onSelect, initial = [] }: SelectionPickerProps): React.JSX.Element {
  const [chosen, setChosen] = useState<readonly string[]>(initial)
  const selected = items.filter((item) => chosen.includes(item.id))
  const toggle = (id: string): void =>
    setChosen((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  return (
    <div onClick={(e) => e.stopPropagation()} style={{ marginTop: 8, display: 'grid', gap: 6 }}>
      <div style={{ maxHeight: 148, overflowY: 'auto', display: 'grid', gap: 4 }}>
        {items.map((item) => (
          <label
            key={item.id}
            style={{
              display: 'flex',
              gap: 8,
              alignItems: 'center',
              fontSize: 11.5,
              cursor: 'pointer'
            }}
          >
            <input
              type="checkbox"
              aria-label={item.name}
              checked={chosen.includes(item.id)}
              onChange={() => toggle(item.id)}
            />
            <span style={{ flex: 1, minWidth: 0 }}>{item.name}</span>
            {item.subtitle && <span style={{ ...SUB, color: 'var(--mut)' }}>{item.subtitle}</span>}
          </label>
        ))}
      </div>
      <Button kind="primary" size="sm" onClick={() => onSelect?.(selected)}>
        Track {selected.length > 0 ? selected.length : 'none'}
      </Button>
    </div>
  )
}

function useRefreshedItems(props: SelectionPickerProps) {
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
        setError('Could not refresh the list. Your selection is unchanged.')
    } finally {
      if (current === generation.current) {
        pending.current = false
        setBusy(false)
      }
    }
  }
  return { items, busy, error, refresh }
}

function PickerBody(props: SelectionPickerProps): React.JSX.Element {
  if (props.sections) return <SectionedPicker {...props} />
  return props.mode === 'multi' ? <MultiPicker {...props} /> : <SinglePicker {...props} />
}

export function SelectionPicker(props: SelectionPickerProps): React.JSX.Element {
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
