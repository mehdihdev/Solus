// SOLUSDEV-233: the SOL page's right-panel "CONTEXT IN USE" — the user's
// standing instruction (editable), plus the last turn's context manifest from
// the context_used frame: document citations as a file list, graph citations
// as entity chips. Labels only — section text never reaches the client.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import type { ContextUsedInfo } from './solStream'
import { useCustomInstruction } from './useCustomInstruction'

/** Strip the citation's [connector:ref] wrapper down to a readable label. */
export function citationLabel(citation: string): string {
  const inner = citation.replace(/^\[/, '').replace(/\]$/, '')
  const at = inner.indexOf(':')
  return at === -1 ? inner : inner.slice(at + 1)
}

const INSTRUCTION_CAP = 500

const INSTRUCTION_TEXTAREA_STYLE: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 4,
  padding: '8px 10px',
  fontSize: 11.5,
  fontFamily: 'var(--font-ui)',
  resize: 'vertical',
  outline: 'none'
}

function CustomInstructionCard(): React.JSX.Element {
  const { instruction, status, save } = useCustomInstruction()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [failed, setFailed] = useState(false)

  const beginEdit = (): void => {
    setDraft(instruction ?? '')
    setFailed(false)
    setEditing(true)
  }
  const submit = async (): Promise<void> => {
    const ok = await save(draft)
    setFailed(!ok)
    if (ok) setEditing(false)
  }

  return (
    <Card pad={12} className="sol-panel-in" style={{ marginTop: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: 12, fontWeight: 600 }}>Custom instruction</div>
        {status === 'ready' && !editing && (
          <Button kind="bare" size="sm" onClick={beginEdit}>
            {instruction ? 'Edit' : 'Add'}
          </Button>
        )}
      </div>
      {!editing && (
        <div
          style={{
            fontSize: 11.5,
            color: instruction ? 'var(--tx)' : 'var(--mut)',
            marginTop: 6,
            lineHeight: 1.5
          }}
        >
          {status === 'offline'
            ? 'Unavailable offline.'
            : (instruction ?? 'None set. SOL follows your saved preferences here.')}
        </div>
      )}
      {editing && (
        <div style={{ marginTop: 8 }}>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            maxLength={INSTRUCTION_CAP}
            rows={3}
            aria-label="Custom instruction"
            placeholder="Prefer metric units. Flag servo commands past URDF limits."
            style={INSTRUCTION_TEXTAREA_STYLE}
          />
          {failed && (
            <div style={{ fontSize: 10.5, color: 'var(--err)', marginTop: 4 }}>
              Couldn&apos;t save — try again.
            </div>
          )}
          <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', marginTop: 6 }}>
            <Button kind="ghost" size="sm" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button kind="primary" size="sm" onClick={() => void submit()}>
              Save
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}

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
              padding: '3px 9px'
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
function manifestFootnote(context: ContextUsedInfo, accounted: number): string | null {
  const other = context.sections.length - accounted
  const parts: string[] = []
  if (other > 0) parts.push(`+ ${other} telemetry/error section${other === 1 ? '' : 's'}`)
  if (context.truncated) parts.push('context truncated to budget')
  return parts.length > 0 ? parts.join(' · ') : null
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
  const graph = context.sections.filter((s) => s.kind === 'graph' && s.citation)
  return (
    <>
      <ContextFilesCard labels={documents.map((s) => citationLabel(s.citation ?? ''))} />
      <GraphChipsCard
        labels={graph.map((s) => citationLabel(s.citation ?? ''))}
        footnote={manifestFootnote(context, documents.length + graph.length)}
      />
    </>
  )
}

export function ContextPanel({
  contextUsed
}: {
  contextUsed: ContextUsedInfo | null
}): React.JSX.Element {
  return (
    <div>
      <Mono size={9.5}>CONTEXT IN USE</Mono>
      <CustomInstructionCard />
      <ManifestCards context={contextUsed} />
    </div>
  )
}
