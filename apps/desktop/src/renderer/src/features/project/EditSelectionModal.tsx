// Change what an already-connected source tracks, without reconnecting. An
// Onshape account spans many documents and a team's selection changes over
// time, so the choice made at connect time must stay editable.
//
// Generic by construction: the connector's declared `selection` supplies the
// noun, the mode, and the config key, and `selectionConfig` turns the choice
// into source config — the same code path the connect flow uses.
import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import {
  listSelectable,
  triggerSync,
  updateSource,
  type IntegrationSelection,
  type SelectableItem
} from '../../lib/api/resources'
import { SelectionPicker } from '../onboarding/SelectionPicker'
import { plural, selectionConfig } from '../onboarding/selectionConfigureStep'
import { ModalShell } from '../workspace/modals'

interface EditSelectionModalProps {
  projectId: string
  sourceId: string
  sourceName: string
  selection: IntegrationSelection
  /** What the source tracks today, so the picker opens on the current choice. */
  current: readonly string[]
  onClose: () => void
  onSaved: () => void
}

type Status = 'loading' | 'ready' | 'saving' | 'error'

const NOTE = { marginTop: 12, fontSize: 12, color: 'var(--mut)' } as const

/** Whatever the modal is showing right now: loading, an honest failure, an empty
 *  account, or the picker itself. */
function Body({
  status,
  error,
  items,
  selection,
  current,
  onSelect
}: {
  status: Status
  error: string | null
  items: readonly SelectableItem[]
  selection: IntegrationSelection
  current: readonly string[]
  onSelect: (items: SelectableItem[] | null) => void
}): React.JSX.Element {
  const listed = status === 'ready' || status === 'saving'
  return (
    <>
      {status === 'loading' && <div style={NOTE}>Loading {plural(selection.label)}…</div>}
      {error && <div style={{ marginTop: 10, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
      {listed && items.length === 0 && (
        <div style={NOTE}>No {plural(selection.label)} found for this account.</div>
      )}
      {listed && items.length > 0 && (
        <SelectionPicker
          items={items}
          mode={selection.mode}
          initial={current}
          onSelect={onSelect}
        />
      )}
    </>
  )
}

export function EditSelectionModal({
  projectId,
  sourceId,
  sourceName,
  selection,
  current,
  onClose,
  onSaved
}: EditSelectionModalProps): React.JSX.Element {
  const [items, setItems] = useState<readonly SelectableItem[]>([])
  const [status, setStatus] = useState<Status>('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listSelectable(projectId, sourceId)
      .then((found) => {
        if (cancelled) return
        setItems(found)
        setStatus('ready')
      })
      .catch(() => {
        if (cancelled) return
        setError(`Couldn't reach ${sourceName} to list its ${plural(selection.label)}.`)
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [projectId, sourceId, sourceName, selection.label])

  const save = async (chosen: SelectableItem[] | null): Promise<void> => {
    if (chosen === null) {
      onClose()
      return
    }
    setStatus('saving')
    try {
      await updateSource(projectId, sourceId, { config: selectionConfig(selection, chosen) })
      // Re-sync so the graph reflects the new selection: newly tracked items are
      // ingested and dropped ones are reconciled away.
      await triggerSync(projectId, sourceId)
      onSaved()
      onClose()
    } catch {
      setError('Could not save the selection. Check your access and try again.')
      setStatus('error')
    }
  }

  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>
        Choose {plural(selection.label)} for {sourceName}
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 }}>
        Only the {plural(selection.label)} you track are indexed into the graph. Removing one keeps
        the entities it already contributed until the next sync reconciles them.
      </div>

      <Body
        status={status}
        error={error}
        items={items}
        selection={selection}
        current={current}
        onSelect={(chosen) => void save(chosen)}
      />

      <div style={{ marginTop: 14, display: 'flex', justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </ModalShell>
  )
}
