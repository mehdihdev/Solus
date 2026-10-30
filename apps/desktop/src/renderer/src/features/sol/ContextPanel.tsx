// SOLUSDEV-233: the SOL page's "CONTEXT IN USE" — the last turn's context manifest from
// the context_used frame: document citations as a file list, graph citations as entity
// chips. Labels only — section text never reaches the client. (The standing instruction
// moved to CustomInstructionCard with the design-template right column.)
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import type { ContextUsedInfo } from './solStream'
import { citationLabel } from './citationLabel'

function ContextFilesCard({ labels }: { labels: readonly string[] }): React.JSX.Element {
  return (
    <Card pad={12} className="sol-panel-in" style={{ marginTop: 10 }}>
      <div style={{ fontSize: 12, fontWeight: 600 }}>Context files</div>
      {labels.length === 0 && (
        <div style={{ fontSize: 11, color: 'var(--mut)', marginTop: 6 }}>
          No files in this turn.
        </div>
      )}
      {labels.map((label, i) => (
        <div
          key={`${label}-${i}`}
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10.5,
            color: 'var(--tx)',
            marginTop: 6,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap'
          }}
        >
          {label}
        </div>
      ))}
    </Card>
  )
}

function GraphChipsCard({
  labels,
  footnote
}: {
  labels: readonly string[]
  footnote: string | null
}): React.JSX.Element {
  return (
    <Card pad={12} className="sol-panel-in" style={{ marginTop: 10 }}>
      <div style={{ fontSize: 12, fontWeight: 600 }}>From the graph</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
        {labels.length === 0 && (
          <span style={{ fontSize: 11, color: 'var(--mut)' }}>No graph context this turn.</span>
        )}
        {labels.map((label, i) => (
          <span
            key={`${label}-${i}`}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10.5,
              color: 'var(--mut)',
              background: 'var(--sur2)',
              border: '1px solid var(--bd)',
              borderRadius: 99,
              padding: '3px 9px',
              maxWidth: '100%',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap'
            }}
          >
            {label}
          </span>
        ))}
      </div>
      {footnote && (
        <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 8 }}>{footnote}</div>
      )}
    </Card>
  )
}

/** The extra-sections/truncation footnote, or null when there is nothing to say. */
function manifestFootnote(context: ContextUsedInfo): string | null {
  // Counted by KIND, never by subtraction — an uncited graph section must not
  // masquerade as telemetry (security review M2).
  const other = context.sections.filter((s) => s.kind === 'telemetry' || s.kind === 'error').length
  const parts: string[] = []
  if (other > 0) parts.push(`+ ${other} telemetry/error section${other === 1 ? '' : 's'}`)
  if (context.truncated) parts.push('context truncated to budget')
  return parts.length > 0 ? parts.join(' · ') : null
}

/** SOLUSDEV-252 S3: the VISUAL_LOG extractor's read of the circled region —
 *  a proposal, labelled as such (sol-window.md §8). */
function ScreenLine({ tokens }: { tokens: number }): React.JSX.Element {
  return (
    <Card pad={12} className="sol-panel-in" style={{ marginTop: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontSize: 12, fontWeight: 600 }}>Screen (tentative read)</div>
        <Mono size={9.5}>{tokens} tokens</Mono>
      </div>
    </Card>
  )
}

function ManifestCards({ context }: { context: ContextUsedInfo | null }): React.JSX.Element {
  if (!context) {
    return (
      <Card pad={12} className="sol-panel-in" style={{ marginTop: 10 }}>
        <div style={{ fontSize: 11.5, color: 'var(--mut)', lineHeight: 1.5 }}>
          Send a message and SOL will show what it grounded the answer in — files, graph entities,
          telemetry.
        </div>
      </Card>
    )
  }
  const documents = context.sections.filter((s) => s.kind === 'document' && s.citation)
  const graphCited = context.sections.filter((s) => s.kind === 'graph' && s.citation)
  // The backend's graph floor carries no citation — it is still real grounding
  // and must show, aggregated (security review M2: a grounding panel that
  // hides the graph misrepresents grounding).
  const graphUncited = context.sections.filter((s) => s.kind === 'graph' && !s.citation).length
  const graphLabels = [
    ...graphCited.map((s) => citationLabel(s.citation ?? '')),
    ...(graphUncited > 0 ? [`graph context ×${graphUncited}`] : [])
  ]
  const screen = context.sections.find((s) => s.kind === 'screen')
  return (
    <>
      <ContextFilesCard labels={documents.map((s) => citationLabel(s.citation ?? ''))} />
      <GraphChipsCard labels={graphLabels} footnote={manifestFootnote(context)} />
      {screen && <ScreenLine tokens={screen.tokens} />}
    </>
  )
}

export function ContextPanel({
  contextUsed
}: {
  contextUsed: ContextUsedInfo | null
}): React.JSX.Element {
  return (
    <section aria-label="Context in use">
      <Mono size={10} ls="0.08em">
        CONTEXT IN USE
      </Mono>
      <ManifestCards context={contextUsed} />
    </section>
  )
}
