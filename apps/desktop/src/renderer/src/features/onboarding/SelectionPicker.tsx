// The picker over whatever a connected source can track — repositories, CAD
// documents, anything a future connector offers. Shared by the connect tile and
// the "edit selection" modal so both stay identical.
//
// Nothing here knows what an item IS: `mode` comes from the connector's declared
// selection, and the item's own `name`/`subtitle` are the only copy shown.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import type { SelectableItem } from '../../lib/api/resources'

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
      <Button
        kind="primary"
        size="sm"
        onClick={() => onSelect?.(items.filter((i) => chosen.includes(i.id)))}
      >
        Track {chosen.length > 0 ? chosen.length : 'none'}
      </Button>
    </div>
  )
}

export function SelectionPicker(props: SelectionPickerProps): React.JSX.Element {
  return props.mode === 'multi' ? <MultiPicker {...props} /> : <SinglePicker {...props} />
}
