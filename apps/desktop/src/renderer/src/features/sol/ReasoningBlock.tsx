// SOLUSDEV-321 P7: what SOL weighed before a proposal, as a collapsible block above the card it
// precedes (docs/wireflows/sol-page.md). The strings are model text that the server parsed out of
// the reply, held to its shape, masked and capped (agent/reasoning_frame.py), and solStream bounded
// again, so they render as text nodes only — never markdown, never HTML, never a link. Guide opens
// the block, where the reasoning is part of the teaching; Expert keeps it shut until asked
// (ADR-016: the mode is universal).
import { useSettingsStore } from '../../store/settingsStore'
import type { CardReasoning, ReasoningInfo } from './solStream'

const MUTED: React.CSSProperties = { fontSize: 11, color: 'var(--mut)' }

const BLOCK: React.CSSProperties = {
  margin: '6px 0',
  padding: '6px 9px',
  border: '1px solid var(--bd)',
  borderRadius: 6,
  background: 'var(--sur2)',
  fontSize: 12,
  lineHeight: 1.45
}

/** The reasoning hung on ONE card (P7 fix 1, M1: mounted per card, so it sits on its own card and
 *  goes with it); reasoning still waiting for its card matches none and shows nowhere. */
export function ReasoningBlock({
  reasoning,
  confirmationId
}: {
  reasoning?: readonly CardReasoning[]
  confirmationId: string
}): React.JSX.Element | null {
  const guide = useSettingsStore((state) => state.solMode === 'Guide')
  const entry = reasoning?.find((candidate) => candidate.confirmationId === confirmationId)
  return entry ? <Block info={entry.reasoning} open={guide} /> : null
}

function Block({ info, open }: { info: ReasoningInfo; open: boolean }): React.JSX.Element {
  return (
    <details data-testid="reasoning-block" open={open} style={BLOCK}>
      <summary style={{ ...MUTED, cursor: 'pointer', userSelect: 'none' }}>SOL’s reasoning</summary>
      <Rows title="Considered" rows={info.considered} />
      <Rows title="Ruled out" rows={info.ruledOut.map((row) => `${row.what} — ${row.why}`)} />
      {info.proposing && (
        <div style={{ marginTop: 4 }}>
          <span style={MUTED}>Proposing </span>
          <span>{info.proposing}</span>
        </div>
      )}
    </details>
  )
}

function Rows({
  title,
  rows
}: {
  title: string
  rows: readonly string[]
}): React.JSX.Element | null {
  if (rows.length === 0) return null
  return (
    <div style={{ marginTop: 4 }}>
      <div style={MUTED}>{title}</div>
      <ul style={{ margin: '2px 0 0', paddingLeft: 16 }}>
        {rows.map((row, i) => (
          <li key={`${i}:${row}`}>{row}</li>
        ))}
      </ul>
    </div>
  )
}
