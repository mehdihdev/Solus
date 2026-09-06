// SOLUSDEV-246 (STORE ST5) — the sourcing panel's phases after the requirement:
// searching (honest wait), failed (typed message + retry), candidates (compare
// → select), selected (planned part + vendor CAD). Small, prop-driven views.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import type { Entity } from '../../lib/api/resources'
import type { SourcingDoor, SourcingRequestApi, TorqueApi } from '../../lib/api/resources.sourcing'
import { CandidateCompare, type CategoryOption } from './CandidateCompare'
import { RulesEditor } from './RulesEditor'
import { rulesSummary, safeHttps, torqueLine } from './sourcingLogic'
import type { SourcingData } from './useSourcing'

const WARN: React.CSSProperties = { fontSize: 12, color: 'var(--warn)', marginTop: 10 }
const ROW: React.CSSProperties = { display: 'flex', gap: 8, marginTop: 12 }

export function Alert({ text }: { text: string | null }): React.JSX.Element | null {
  return text ? (
    <div role="alert" style={WARN}>
      {text}
    </div>
  ) : null
}

export function RulesLine({ data }: { data: SourcingData }): React.JSX.Element {
  const [editing, setEditing] = useState(false)
  const rules = data.rules
  return (
    <div style={{ marginTop: 14, fontSize: 12, color: 'var(--mut)' }}>
      <span data-testid="sourcing-rules-line">Project rules: {rulesSummary(rules)}</span>
      {rules && !editing && (
        <Button kind="bare" size="sm" onClick={() => setEditing(true)}>
          Edit rules
        </Button>
      )}
      {rules && editing && (
        <RulesEditor
          rules={rules}
          onSave={data.actions.saveRules}
          onClose={() => setEditing(false)}
        />
      )}
    </div>
  )
}

export function SearchingView({ torque }: { torque: TorqueApi | null }): React.JSX.Element {
  return (
    <div
      data-testid="sourcing-searching"
      style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '28px 0', fontSize: 12.5 }}
    >
      <Spinner size={16} />
      <span>
        Solus is finding candidates{torque ? ` for ${torqueLine(torque).toLowerCase()}` : ''}…
      </span>
    </div>
  )
}

export function FailedView({
  error,
  onRetry
}: {
  error: string | null
  onRetry: () => void
}): React.JSX.Element {
  return (
    <div>
      <Alert text={error ?? 'Sourcing did not finish.'} />
      <div style={{ ...ROW, justifyContent: 'flex-end' }}>
        <Button kind="soft" size="sm" onClick={onRetry}>
          Try again
        </Button>
      </div>
    </div>
  )
}

export function CandidatesView({
  request,
  categories,
  busy,
  error,
  onSelect,
  onBack
}: {
  request: SourcingRequestApi
  categories: readonly CategoryOption[]
  busy: boolean
  error: string | null
  onSelect: (candidateId: string, categoryId: string | undefined, quantity: number) => void
  onBack: () => void
}): React.JSX.Element {
  return (
    <div style={{ marginTop: 12 }}>
      {request.torque && (
        <div style={{ fontSize: 12, color: 'var(--mut)', marginBottom: 10 }}>
          {torqueLine(request.torque)}
        </div>
      )}
      <CandidateCompare
        candidates={request.candidates}
        excluded={request.excluded}
        currency="USD"
        categories={categories}
        busy={busy}
        onSelect={onSelect}
      />
      <Alert text={error} />
      <div style={ROW}>
        <Button kind="bare" size="sm" onClick={onBack}>
          ← Change the requirement
        </Button>
      </div>
    </div>
  )
}

export function SelectedView({
  entity,
  door,
  onAnother,
  onDone
}: {
  entity: Entity
  door: SourcingDoor
  onAnother: () => void
  onDone: () => void
}): React.JSX.Element {
  const cad = safeHttps(entity.properties?.vendor_cad_url as string | undefined)
  const where =
    door === 'workspace' ? ' under the category you chose — see it in the Workspace' : ''
  return (
    <div style={{ marginTop: 12 }} data-testid="sourcing-selected">
      <div style={{ fontSize: 14, fontWeight: 600 }}>{entity.name} is planned</div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 6, lineHeight: 1.5 }}>
        It entered the project graph as a planned part{where}; the BOM lists it as PLANNED.
      </div>
      {cad ? (
        <a
          href={cad}
          target="_blank"
          rel="noopener noreferrer"
          style={{ display: 'inline-block', marginTop: 10, fontSize: 12.5 }}
        >
          Get vendor CAD model ↗
        </a>
      ) : (
        <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 10 }}>
          No vendor CAD model was cited for this part.
        </div>
      )}
      <div style={{ ...ROW, justifyContent: 'flex-end', marginTop: 16 }}>
        <Button kind="ghost" size="sm" onClick={onAnother}>
          Source another
        </Button>
        <Button kind="primary" size="sm" onClick={onDone}>
          Done
        </Button>
      </div>
    </div>
  )
}

export function PanelHeader({
  door,
  onClose
}: {
  door: SourcingDoor
  onClose: () => void
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <Mono size={9.5}>
        {door === 'workspace' ? 'ADD A SOURCED PART' : 'FIND COMPATIBLE PARTS'}
      </Mono>
      <span style={{ flex: 1 }} />
      <Button kind="bare" size="sm" onClick={onClose} aria-label="Close">
        ✕
      </Button>
    </div>
  )
}
