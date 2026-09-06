// SOLUSDEV-246 / STORE ST4 — pure presentation rules for the BOM page:
// money and quantity formatting, the state palette, and the honest one-line
// notes about what the view could not learn. No fetch, no store.
import type {
  BomItemCategory,
  BomItemInput,
  BomLifecycleState,
  BomRowApi,
  BomRowKind,
  BomViewApi
} from '../../lib/api/resources.bom'

export const STATE_LABEL: Readonly<Record<BomLifecycleState, string>> = {
  planned: 'Planned',
  ordered: 'Ordered',
  received: 'Received',
  installed: 'Installed',
  retired: 'Retired'
}

export const KIND_LABEL: Readonly<Record<BomRowKind, string>> = {
  design: 'DESIGN',
  purchase: 'PURCHASE',
  raw_material: 'RAW MATERIAL'
}

/** State → theme colour token; `installed` reads as done, `retired` as muted. */
export function stateColor(state: BomLifecycleState): string {
  switch (state) {
    case 'installed':
      return 'var(--ok)'
    case 'received':
      return 'var(--acc)'
    case 'retired':
      return 'var(--mut)'
    default:
      return 'var(--warn)'
  }
}

export function formatMoney(value: number | null, currency: string): string {
  if (value === null) return '—'
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(value)
  } catch {
    return `${value.toFixed(2)} ${currency}`
  }
}

/** "electrical: U3 · mechanical: Servo body" — where a design row was observed. */
export function sourcesLine(row: BomRowApi): string {
  return row.sources.map((s) => `${s.domain}: ${s.name}`).join(' · ')
}

/** The totals strip: rows, priced rows, sum and the cost-target verdict. */
export function totalsLine(view: BomViewApi): string {
  const { totals, config } = view
  const parts = [
    `${totals.rows} ${totals.rows === 1 ? 'row' : 'rows'}`,
    `${totals.priced_rows} priced`,
    `total ${formatMoney(totals.line_cost_total, config.currency)}`
  ]
  if (totals.cost_target !== null) {
    parts.push(
      `${totals.over_target ? 'over' : 'within'} target ${formatMoney(totals.cost_target, config.currency)}`
    )
  }
  return parts.join(' · ')
}

/** One honest line about the view's limits, or null. */
export function viewNote(view: BomViewApi): string | null {
  if (view.truncated)
    return 'This project has more parts than the BOM can list at once; the rows below are a bounded subset.'
  return null
}

/** A CSV filename that is safe for every OS file dialog. */
export function csvFilename(projectName: string): string {
  const stem = projectName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return `bom-${stem || 'project'}.csv`
}

// ---------------------------------------------------------------- add-row form

export interface AddRowForm {
  name: string
  category: BomItemCategory
  quantity: string
  partNumber: string
  supplier: string
  unitCost: string
}

export const EMPTY_ADD_ROW_FORM: AddRowForm = {
  name: '',
  category: 'purchase',
  quantity: '1',
  partNumber: '',
  supplier: '',
  unitCost: ''
}

/** A blank string means "not given"; otherwise a number the caller validates. */
function optionalNumber(raw: string): number | undefined {
  return raw.trim() === '' ? undefined : Number(raw)
}

function optionalText(raw: string): string | undefined {
  return raw.trim() ? raw.trim() : undefined
}

function firstProblem(name: string, quantity?: number, unitCost?: number): string | null {
  if (!name) return 'Give the row a name.'
  if (quantity !== undefined && (!Number.isInteger(quantity) || quantity < 1))
    return 'Quantity must be a whole number of at least 1.'
  if (unitCost !== undefined && (!Number.isFinite(unitCost) || unitCost < 0))
    return 'Unit cost must be zero or more.'
  return null
}

/** The request body from the form's strings: only fields the user filled in. */
export function itemInputFrom(form: AddRowForm): BomItemInput | { error: string } {
  const name = form.name.trim()
  const quantity = optionalNumber(form.quantity)
  const unitCost = optionalNumber(form.unitCost)
  const error = firstProblem(name, quantity, unitCost)
  if (error) return { error }
  const optional = {
    quantity,
    part_number: optionalText(form.partNumber),
    supplier: optionalText(form.supplier),
    unit_cost: unitCost
  }
  const given = Object.fromEntries(Object.entries(optional).filter(([, v]) => v !== undefined))
  return { name, category: form.category, ...given }
}
