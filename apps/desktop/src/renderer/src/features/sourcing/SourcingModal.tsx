// SOLUSDEV-246 (STORE ST5) — ONE sourcing panel for two doors: Workspace › Add
// › Hardware › Sourced (a Physical Robot's category receives the part) and
// BOM › Find compatible parts. Requirement → Solus finds candidates (a metered
// job) → compare side by side → Select → the part enters the graph as PLANNED.
import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import type { Entity } from '../../lib/api/resources'
import { listEntities } from '../../lib/api/resources'
import type { SourcingDoor } from '../../lib/api/resources.sourcing'
import { ModalShell } from '../workspace/modals'
import type { CategoryOption } from './CandidateCompare'
import { RequirementStep, type CadState, type RequirementMode } from './RequirementStep'
import {
  Alert,
  CandidatesView,
  FailedView,
  PanelHeader,
  RulesLine,
  SearchingView,
  SelectedView
} from './SourcingPhases'
import { EMPTY_SPEC_FORM, massesFrom, requestInputFrom, type SpecForm } from './sourcingLogic'
import { useSourcing, type SourcingData } from './useSourcing'

export interface SourcingModalProps {
  projectId: string
  door: SourcingDoor
  onClose: () => void
  /** The planned part just created — the door refreshes what it shows. */
  onSelected?: (entity: Entity) => void
  /** Test seam. */
  sourcing?: SourcingData
}

const CATEGORY_LIMIT = 100

/** The Physical Robot categories a sourced part can land under (Workspace door only). */
function useCategories(projectId: string, door: SourcingDoor): CategoryOption[] {
  const [categories, setCategories] = useState<CategoryOption[]>([])
  useEffect(() => {
    if (door !== 'workspace') return
    let cancelled = false
    listEntities(projectId, { type: 'robot_category', limit: CATEGORY_LIMIT }).then(
      (rows) => {
        if (!cancelled) setCategories(rows.map((r) => ({ id: r.id, label: r.name })))
      },
      () => undefined
    )
    return () => {
      cancelled = true
    }
  }, [projectId, door])
  return categories
}

function RequirementPhase({
  projectId,
  door,
  data
}: {
  projectId: string
  door: SourcingDoor
  data: SourcingData
}): React.JSX.Element {
  const [form, setForm] = useState<SpecForm>(EMPTY_SPEC_FORM)
  const [mode, setMode] = useState<RequirementMode>(door === 'workspace' ? 'From CAD' : 'Describe')
  const [cad, setCad] = useState<CadState>({ assemblyId: '', masses: {} })
  const [formError, setFormError] = useState<string | null>(null)
  const fromCad = mode === 'From CAD' && cad.assemblyId !== ''
  const masses = massesFrom(cad.masses)

  const find = (): void => {
    const context = fromCad ? { door, assemblyId: cad.assemblyId, masses } : { door }
    const input = requestInputFrom(form, context)
    if ('error' in input) {
      setFormError(input.error)
      return
    }
    setFormError(null)
    void data.actions.submit(input)
  }

  return (
    <>
      <RequirementStep
        projectId={projectId}
        form={form}
        onForm={setForm}
        mode={mode}
        onMode={setMode}
        cad={cad}
        onCad={setCad}
        torque={mode === 'From CAD' ? data.torque : null}
        busy={data.busy}
        onDerive={() => void data.actions.derive({ assembly_entity_id: cad.assemblyId, masses })}
      />
      <RulesLine data={data} />
      <Alert text={formError ?? data.error} />
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
        <Button kind="primary" size="sm" disabled={data.busy} onClick={find}>
          Find candidates
        </Button>
      </div>
    </>
  )
}

export function SourcingModal(props: SourcingModalProps): React.JSX.Element {
  const { projectId, door, onClose, onSelected } = props
  const own = useSourcing(projectId)
  const data = props.sourcing ?? own
  const categories = useCategories(projectId, door)
  const { phase, actions } = data

  return (
    <ModalShell onClose={onClose} width={860}>
      <div role="dialog" aria-modal="true" aria-label="Find a part">
        <PanelHeader door={door} onClose={onClose} />
        {phase === 'requirement' && (
          <RequirementPhase projectId={projectId} door={door} data={data} />
        )}
        {phase === 'searching' && <SearchingView torque={data.torque} />}
        {phase === 'failed' && <FailedView error={data.error} onRetry={actions.reset} />}
        {phase === 'candidates' && data.request && (
          <CandidatesView
            request={data.request}
            categories={door === 'workspace' ? categories : []}
            busy={data.busy}
            error={data.error}
            onBack={actions.reset}
            onSelect={(candidateId, categoryId, quantity) =>
              void actions.select(candidateId, {
                ...(categoryId ? { category_entity_id: categoryId } : {}),
                quantity
              })
            }
          />
        )}
        {phase === 'selected' && data.selected && (
          <SelectedView
            entity={data.selected}
            door={door}
            onAnother={actions.reset}
            onDone={() => {
              if (data.selected) onSelected?.(data.selected)
              onClose()
            }}
          />
        )}
      </div>
    </ModalShell>
  )
}
