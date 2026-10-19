// The .solus line in Home's PROJECT SETUP (SOLUSDEV-317, concept 1): five
// segments for the five sections (filled = holds something), "N of 5
// sections filled", the filled sections with their counts, and "Add
// instructions" (the pane opens its .solus tab, where notes are written).
// Honest loading and offline states; the full card stays on the .solus tab.
import { SOLUS_SECTIONS } from '../../lib/api/resources'
import { SECTION_LABELS, useSolusConfig } from '../graph/useSolusConfig'

export interface SolusSummaryRowProps {
  projectId: string
  onAddInstructions: () => void
}

export function SolusSummaryRow({
  projectId,
  onAddInstructions
}: SolusSummaryRowProps): React.JSX.Element {
  const solus = useSolusConfig(projectId)
  const filled = SOLUS_SECTIONS.filter((s) => solus.sections[s].length > 0)
  return (
    <div style={ROW}>
      <span aria-hidden="true" style={MARK}>
        .s
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
          {SOLUS_SECTIONS.map((s) => (
            <span
              key={s}
              data-testid="solus-segment"
              data-filled={String(filled.includes(s))}
              title={SECTION_LABELS[s]}
              style={{
                width: 34,
                height: 4,
                borderRadius: 2,
                background: filled.includes(s) ? 'var(--acc)' : 'var(--bd)'
              }}
            />
          ))}
        </div>
        <div style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.45 }}>
          {summaryText(solus.status, filled, solus.sections)}
        </div>
      </div>
      <button type="button" className="interactive" onClick={onAddInstructions} style={LINK}>
        Add instructions
      </button>
    </div>
  )
}

function summaryText(
  status: ReturnType<typeof useSolusConfig>['status'],
  filled: readonly (typeof SOLUS_SECTIONS)[number][],
  sections: ReturnType<typeof useSolusConfig>['sections']
): string {
  if (status === 'loading') return 'Loading…'
  if (status === 'offline') return "Solus can't reach its API — .solus appears when it does."
  if (filled.length === 0) return 'Nothing yet — tell SOL how this project works.'
  const named = filled.map((s) => `${SECTION_LABELS[s]} (${sections[s].length})`).join(' · ')
  return `${filled.length} of ${SOLUS_SECTIONS.length} sections filled · ${named}`
}

const ROW: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '32px minmax(0, 1fr) auto',
  gap: 12,
  alignItems: 'center'
}

const MARK: React.CSSProperties = {
  width: 28,
  height: 28,
  borderRadius: 6,
  background: 'var(--sur2)',
  border: '1px solid var(--bd)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  color: 'var(--acc)'
}

const LINK: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  color: 'var(--acc)',
  cursor: 'pointer',
  fontFamily: 'var(--font-ui)',
  fontSize: 12,
  padding: 0,
  whiteSpace: 'nowrap'
}
