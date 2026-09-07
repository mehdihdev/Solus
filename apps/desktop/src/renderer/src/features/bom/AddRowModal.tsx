// SOLUSDEV-246 / STORE ST4 — "Add row": a purchase or raw material the design
// does not know about (a motor still being sourced, stock plate). Starts as
// `planned`. The server re-validates every field (widget-bundles.md §11); this
// is first-line validation and honest error display only.
import { useId, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import type { BomItemInput } from '../../lib/api/resources.bom'
import { EMPTY_ADD_ROW_FORM, itemInputFrom, type AddRowForm } from './bomLogic'
import { MODAL_INPUT_STYLE, ModalShell } from '../workspace/modals'
import type { BomOutcome } from './useBom'

const INPUT: React.CSSProperties = { ...MODAL_INPUT_STYLE, marginTop: 6 }
const LABEL: React.CSSProperties = { display: 'block', marginTop: 14 }

function TextField({
  label,
  value,
  onChange,
  inputMode,
  autoFocus
}: {
  label: string
  value: string
  onChange: (value: string) => void
  inputMode?: 'numeric' | 'decimal'
  autoFocus?: boolean
}): React.JSX.Element {
  const id = useId()
  return (
    <label htmlFor={id} style={LABEL}>
      <Mono size={9}>{label}</Mono>
      <input
        id={id}
        value={value}
        inputMode={inputMode}
        autoFocus={autoFocus}
        onChange={(e) => onChange(e.target.value)}
        style={INPUT}
      />
    </label>
  )
}

export function AddRowModal({
  onAdd,
  onClose
}: {
  onAdd: (input: BomItemInput) => Promise<BomOutcome>
  onClose: () => void
}): React.JSX.Element {
  const categoryId = useId()
  const [form, setForm] = useState<AddRowForm>(EMPTY_ADD_ROW_FORM)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const set = (key: keyof AddRowForm) => (value: string) => setForm((f) => ({ ...f, [key]: value }))

  const submit = async (): Promise<void> => {
    const input = itemInputFrom(form)
    if ('error' in input) {
      setError(input.error)
      return
    }
    setBusy(true)
    const outcome = await onAdd(input)
    setBusy(false)
    if (outcome.ok) onClose()
    else setError(outcome.message)
  }

  return (
    <ModalShell onClose={onClose} width={420}>
      <div role="dialog" aria-modal="true" aria-label="Add a BOM row">
        <Mono size={9.5}>ADD A BOM ROW</Mono>
        <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 6, lineHeight: 1.5 }}>
          Something the design does not know about yet — a purchase being sourced, or a raw
          material. Parts already in CAD or the schematic list themselves.
        </div>
        <TextField label="Name" value={form.name} onChange={set('name')} autoFocus />
        <label htmlFor={categoryId} style={LABEL}>
          <Mono size={9}>Category</Mono>
          <select
            id={categoryId}
            value={form.category}
            onChange={(e) => set('category')(e.target.value)}
            style={INPUT}
          >
            <option value="purchase">Purchase</option>
            <option value="raw_material">Raw material</option>
          </select>
        </label>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <TextField
            label="Quantity"
            value={form.quantity}
            onChange={set('quantity')}
            inputMode="numeric"
          />
          <TextField
            label="Unit cost"
            value={form.unitCost}
            onChange={set('unitCost')}
            inputMode="decimal"
          />
        </div>
        <TextField label="Part number" value={form.partNumber} onChange={set('partNumber')} />
        <TextField label="Supplier" value={form.supplier} onChange={set('supplier')} />
        {error && (
          <div role="alert" style={{ fontSize: 12, color: 'var(--warn)', marginTop: 12 }}>
            {error}
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 18 }}>
          <Button kind="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button kind="primary" size="sm" disabled={busy} onClick={() => void submit()}>
            {busy ? 'Adding…' : 'Add to BOM'}
          </Button>
        </div>
      </div>
    </ModalShell>
  )
}
