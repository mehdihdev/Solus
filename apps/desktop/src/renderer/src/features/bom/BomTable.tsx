// SOLUSDEV-246 / STORE ST4 — the BOM rows. One `<tr>` per physical part; the
// lifecycle state is a select on every row; item rows (purchases and raw
// materials) can be removed, design rows cannot — they come from the tools.
import { Mono } from '../../components/ui/Mono'
import type { BomLifecycleState, BomRowApi } from '../../lib/api/resources.bom'
import { KIND_LABEL, STATE_LABEL, formatMoney, sourcesLine, stateColor } from './bomLogic'

const CELL: React.CSSProperties = {
  padding: '9px 10px',
  borderBottom: '1px solid var(--bd)',
  fontSize: 12.5,
  verticalAlign: 'top'
}
const HEAD: React.CSSProperties = {
  ...CELL,
  textAlign: 'left',
  color: 'var(--mut)',
  fontWeight: 500,
  whiteSpace: 'nowrap'
}
const SELECT: React.CSSProperties = {
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '4px 8px',
  fontSize: 12,
  fontFamily: 'var(--font-ui)'
}

export function BomTable({
  rows,
  states,
  currency,
  onState,
  onRemove
}: {
  rows: readonly BomRowApi[]
  states: readonly BomLifecycleState[]
  currency: string
  onState: (key: string, state: BomLifecycleState) => void
  onRemove: (row: BomRowApi) => void
}): React.JSX.Element {
  return (
    <div style={{ overflowX: 'auto', border: '1px solid var(--bd)', borderRadius: 4 }}>
      <table
        aria-label="Bill of materials"
        style={{ width: '100%', borderCollapse: 'collapse', minWidth: 860 }}
      >
        <thead>
          <tr>
            <th style={HEAD}>Part</th>
            <th style={HEAD}>Kind</th>
            <th style={{ ...HEAD, textAlign: 'right' }}>Qty</th>
            <th style={HEAD}>State</th>
            <th style={HEAD}>Supplier</th>
            <th style={{ ...HEAD, textAlign: 'right' }}>Unit</th>
            <th style={{ ...HEAD, textAlign: 'right' }}>Line</th>
            <th style={HEAD} />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} aria-label={row.name} data-kind={row.kind}>
              <td style={CELL}>
                <div style={{ fontWeight: 600 }}>{row.name}</div>
                {row.manufacturer && (
                  <div style={{ fontSize: 11.5, color: 'var(--mut)' }}>{row.manufacturer}</div>
                )}
                {row.sources.length > 0 && (
                  <div style={{ fontSize: 11, color: 'var(--mut)', marginTop: 2 }}>
                    {sourcesLine(row)}
                  </div>
                )}
                {row.notes && (
                  <div style={{ fontSize: 11.5, marginTop: 4, whiteSpace: 'pre-wrap' }}>
                    {row.notes}
                  </div>
                )}
              </td>
              <td style={CELL}>
                <Mono size={9} color="var(--mut)">
                  {KIND_LABEL[row.kind]}
                </Mono>
              </td>
              <td style={{ ...CELL, textAlign: 'right' }}>{row.quantity}</td>
              <td style={CELL}>
                <select
                  aria-label={`Lifecycle state of ${row.name}`}
                  value={row.state}
                  onChange={(e) => onState(row.key, e.target.value as BomLifecycleState)}
                  style={{ ...SELECT, color: stateColor(row.state) }}
                >
                  {states.map((state) => (
                    <option key={state} value={state}>
                      {STATE_LABEL[state]}
                    </option>
                  ))}
                </select>
              </td>
              <td style={CELL}>{row.supplier ?? <span style={{ color: 'var(--mut)' }}>—</span>}</td>
              <td style={{ ...CELL, textAlign: 'right' }}>
                {formatMoney(row.unit_cost, currency)}
              </td>
              <td style={{ ...CELL, textAlign: 'right' }}>
                {formatMoney(row.line_cost, currency)}
              </td>
              <td style={{ ...CELL, textAlign: 'right', whiteSpace: 'nowrap' }}>
                {row.kind !== 'design' && (
                  <button
                    type="button"
                    aria-label={`Remove ${row.name}`}
                    className="interactive"
                    onClick={() => onRemove(row)}
                    style={{
                      background: 'transparent',
                      border: 'none',
                      color: 'var(--mut)',
                      cursor: 'pointer',
                      fontSize: 12,
                      fontFamily: 'var(--font-ui)'
                    }}
                  >
                    Remove
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
