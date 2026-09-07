// SOLUSDEV-246 (STORE ST5) — candidates side by side. One column per included
// candidate: what it optimises for and what it gives up (always), grounding
// (CITED with its source, or UNVERIFIED with no price and no stock), the
// rules pass's flags, then the comparison rows. Excluded candidates follow
// with the rule text as the reason — Solus's words, never the model's.
import { Fragment, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import type { CandidateApi, ExcludedCandidateApi } from '../../lib/api/resources.sourcing'
import {
  compareColumns,
  defaultCategory,
  groundingLabel,
  linkHost,
  safeHttps,
  tradeOffLine,
  type CategoryOption
} from './sourcingLogic'

export type { CategoryOption }

const CELL: React.CSSProperties = {
  padding: '7px 10px',
  borderBottom: '1px solid var(--bd)',
  fontSize: 12.5,
  verticalAlign: 'top'
}
const INPUT: React.CSSProperties = {
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '5px 8px',
  fontSize: 12,
  fontFamily: 'var(--font-ui)'
}

function GroundingBadge({ candidate }: { candidate: CandidateApi }): React.JSX.Element {
  const cited = candidate.grounding === 'cited'
  const source = safeHttps(candidate.source_url)
  return (
    <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
      <Mono size={8.5} ls="0.12em" color={cited ? 'var(--ok)' : 'var(--warn)'}>
        {groundingLabel(candidate)}
      </Mono>
      {cited && source && (
        <a href={source} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11 }}>
          {linkHost(source)} ↗
        </a>
      )}
    </span>
  )
}

function SelectRow({
  candidate,
  categories,
  busy,
  onSelect
}: {
  candidate: CandidateApi
  categories: readonly CategoryOption[]
  busy: boolean
  onSelect: (candidateId: string, categoryId: string | undefined, quantity: number) => void
}): React.JSX.Element {
  // Categories load after the table mounts: an explicit pick wins, otherwise the default.
  const [picked, setPicked] = useState<string | null>(null)
  const category =
    picked !== null && categories.some((c) => c.id === picked)
      ? picked
      : defaultCategory(categories)
  const [quantity, setQuantity] = useState('1')
  const qty = Number(quantity)
  const valid = Number.isInteger(qty) && qty >= 1
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {categories.length > 0 && (
        <select
          aria-label={`Category for ${candidate.name}`}
          value={category}
          onChange={(e) => setPicked(e.target.value)}
          style={INPUT}
        >
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
      )}
      <input
        aria-label={`Quantity for ${candidate.name}`}
        inputMode="numeric"
        value={quantity}
        onChange={(e) => setQuantity(e.target.value)}
        style={{ ...INPUT, width: 70 }}
      />
      <Button
        kind="primary"
        size="sm"
        disabled={busy || !valid}
        onClick={() => onSelect(candidate.id, category || undefined, qty)}
      >
        Select {candidate.name}
      </Button>
    </div>
  )
}

export function CandidateCompare({
  candidates,
  excluded,
  currency,
  categories,
  busy,
  onSelect
}: {
  candidates: readonly CandidateApi[]
  excluded: readonly ExcludedCandidateApi[]
  currency: string
  categories: readonly CategoryOption[]
  busy: boolean
  onSelect: (candidateId: string, categoryId: string | undefined, quantity: number) => void
}): React.JSX.Element {
  const rows = compareColumns(candidates, currency)
  return (
    <div>
      {candidates.length === 0 ? (
        <p style={{ fontSize: 12.5, color: 'var(--mut)' }}>
          No candidate passed this project&apos;s rules. Loosen a rule below or describe the
          requirement differently.
        </p>
      ) : (
        <div style={{ overflowX: 'auto', border: '1px solid var(--bd)', borderRadius: 4 }}>
          <table
            aria-label="Candidate comparison"
            style={{ borderCollapse: 'collapse', minWidth: 640 }}
          >
            <thead>
              <tr>
                <th style={CELL} />
                {candidates.map((c) => (
                  <th key={c.id} scope="col" style={{ ...CELL, textAlign: 'left', minWidth: 220 }}>
                    <div style={{ fontWeight: 600 }}>{c.name}</div>
                    {c.manufacturer && (
                      <div style={{ fontSize: 11.5, color: 'var(--mut)' }}>{c.manufacturer}</div>
                    )}
                    <div style={{ marginTop: 4 }}>
                      <GroundingBadge candidate={c} />
                    </div>
                    <div style={{ fontSize: 11.5, marginTop: 6, fontWeight: 400 }}>
                      {tradeOffLine(c)}
                    </div>
                    {c.flags.map((flag) => (
                      <div key={flag} style={{ fontSize: 11, color: 'var(--warn)', marginTop: 2 }}>
                        {flag}
                      </div>
                    ))}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.label}>
                  <th
                    scope="row"
                    style={{ ...CELL, textAlign: 'left', color: 'var(--mut)', fontWeight: 500 }}
                  >
                    {row.label}
                  </th>
                  {row.values.map((value, i) => (
                    <td key={`${row.label}-${candidates[i]?.id}`} style={CELL}>
                      {value}
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <th
                  scope="row"
                  style={{ ...CELL, textAlign: 'left', color: 'var(--mut)', fontWeight: 500 }}
                >
                  Vendor CAD
                </th>
                {candidates.map((c) => {
                  const cad = safeHttps(c.vendor_cad_url)
                  return (
                    <td key={`cad-${c.id}`} style={CELL}>
                      {cad ? (
                        <a href={cad} target="_blank" rel="noopener noreferrer">
                          {linkHost(cad)} ↗
                        </a>
                      ) : (
                        '—'
                      )}
                    </td>
                  )
                })}
              </tr>
              <tr>
                <th scope="row" style={{ ...CELL, borderBottom: 'none' }} />
                {candidates.map((c) => (
                  <td key={`select-${c.id}`} style={{ ...CELL, borderBottom: 'none' }}>
                    <SelectRow
                      candidate={c}
                      categories={categories}
                      busy={busy}
                      onSelect={onSelect}
                    />
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {excluded.length > 0 && (
        <div style={{ marginTop: 16 }} data-testid="sourcing-excluded">
          <Mono size={9.5}>EXCLUDED BY THIS PROJECT&apos;S RULES</Mono>
          {excluded.map(({ candidate, reasons }) => (
            <Fragment key={candidate.id}>
              <div style={{ fontSize: 12.5, marginTop: 8, fontWeight: 600 }}>{candidate.name}</div>
              {reasons.map((reason) => (
                <div key={reason} style={{ fontSize: 12, color: 'var(--mut)' }}>
                  {reason}
                </div>
              ))}
            </Fragment>
          ))}
        </div>
      )}
    </div>
  )
}
