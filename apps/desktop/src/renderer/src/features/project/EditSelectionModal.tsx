// Change what an already-connected source tracks, without reconnecting. An
// Onshape account spans many documents and a team's selection changes over
// time, so the choice made at connect time must stay editable.
//
// Generic by construction: the connector's declared `selection` supplies the
// noun, the mode, and the config key, and `selectionConfig` turns the choice
// into source config — the same code path the connect flow uses.
import { useEffect, useState } from 'react'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import {
  listSelectable,
  triggerSync,
  updateSource,
  type IntegrationSelection,
  type SelectableItem
} from '../../lib/api/resources'
import { SelectionPicker } from '../onboarding/SelectionPicker'
import { selectionDiff } from '../onboarding/pickerModel'
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
  /** Saved: how many items the edit added and removed. */
  onSaved: (change: SavedChange) => void
}

export interface SavedChange {
  added: number
  removed: number
}

type Status = 'loading' | 'ready' | 'saving' | 'error'

/** Whatever the modal is showing right now: loading, an honest failure, or the
 *  picker (which owns its own empty state, Save and Cancel). */
function Body({
  status,
  error,
  items,
  selection,
  current,
  onSelect,
  onCancel,
  onRefresh
}: {
  status: Status
  error: string | null
  items: readonly SelectableItem[]
  selection: IntegrationSelection
  current: readonly string[]
  onSelect: (items: SelectableItem[] | null) => void
  onCancel: () => void
  onRefresh: () => Promise<SelectableItem[]>
}): React.JSX.Element {
  const listed = status === 'ready' || status === 'saving'
  return (
    <div style={{ marginTop: 14, display: 'grid', gap: 10 }}>
      {status === 'loading' && (
        <div
          role="status"
          style={{
            display: 'flex',
            gap: 8,
            alignItems: 'center',
            fontSize: 12,
            color: 'var(--mut)'
          }}
        >
          <Spinner size={11} /> Loading {plural(selection.label)}…
        </div>
      )}
      {error && (
        <div role="alert" style={{ fontSize: 11.5, color: 'var(--err)' }}>
          {error}
        </div>
      )}
      {listed && (
        <SelectionPicker
          items={items}
          mode={selection.mode}
          label={selection.label}
          variant="edit"
          initial={current}
          onSelect={onSelect}
          onCancel={onCancel}
          onRefresh={onRefresh}
          disabled={status === 'saving'}
        />
      )}
    </div>
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
    setStatus('loading')
    setError(null)
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
      // Count only what was still listed — the picker's own diff does the same,
      // so the row's notice matches the footer the user just confirmed.
      const listed = new Set(items.map((item) => item.id))
      const diff = selectionDiff(
        current.filter((id) => listed.has(id)),
        chosen.map((item) => item.id)
      )
      onSaved({ added: diff.added.length, removed: diff.removed.length })
      onClose()
    } catch {
      setError('Could not save the selection. Check your access and try again.')
      setStatus('error')
    }
  }

  return (
    <ModalShell onClose={onClose}>
      <SelectionHeading selection={selection} sourceName={sourceName} tracked={current.length} />

      <Body
        key={`${projectId}:${sourceId}`}
        status={status}
        error={error}
        items={items}
        selection={selection}
        current={current}
        onSelect={(chosen) => void save(chosen)}
        onCancel={onClose}
        onRefresh={() => listSelectable(projectId, sourceId, undefined, { refresh: true })}
      />
    </ModalShell>
  )
}

function SelectionHeading({
  selection,
  sourceName,
  tracked
}: Pick<EditSelectionModalProps, 'selection' | 'sourceName'> & {
  tracked: number
}): React.JSX.Element {
  return (
    <div style={{ display: 'grid', gap: 4 }}>
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>
        Edit tracked {plural(selection.label)}
      </h2>
      <Mono size={10}>
        {sourceName} · {tracked} tracked
      </Mono>
    </div>
  )
}
