import { useEffect, useState } from 'react'
import { ApiError } from '../../../lib/api/envelope.types'
import {
  getEntityHardwareConfig,
  putEntityHardwareConfig,
  type EntityHardwareConfigOut
} from '../../../lib/api/hardware'
import { useSettingsStore } from '../../../store/settingsStore'
import { configDraft, hardwareSourceRefs, prepareHardwareConfig } from './hardwareConfigDraft'
import { HardwareSourcesPanel } from './HardwareSourcesPanel'
import { useHardwareGeneration } from './useHardwareGeneration'

function useHardwareConfigDraft(projectId: string, entityId: string, online: boolean) {
  const mode = useSettingsStore((state) => state.solMode)
  const { generation, authEpoch } = useHardwareGeneration(`${projectId}:${entityId}`)
  const [saved, setSaved] = useState<EntityHardwareConfigOut | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let active = true
    const ticket = generation.current
    setSaved(null)
    setDraft('')
    setError(null)
    setStatus(null)
    if (!online) return
    setBusy(true)
    void getEntityHardwareConfig(projectId, entityId).then(
      (result) => {
        if (!active || ticket !== generation.current) return
        if (
          result.entity_id !== entityId ||
          (result.config !== null && result.config.entity_id !== entityId)
        ) {
          setError('Configuration identity changed. Reload the project.')
        } else {
          setSaved(result)
          setDraft(
            configDraft(result.config ?? { schema_version: 2, entity_id: entityId, provenance: {} })
          )
        }
        setBusy(false)
      },
      () => {
        if (active && ticket === generation.current) {
          setError('Could not load configuration. Try reloading.')
          setBusy(false)
        }
      }
    )
    return () => {
      active = false
    }
  }, [projectId, entityId, online, authEpoch, reload, generation])

  return {
    mode,
    generation,
    saved,
    setSaved,
    draft,
    setDraft,
    busy,
    setBusy,
    error,
    setError,
    status,
    setStatus,
    setReload
  }
}

function useHardwareConfigEditor(projectId: string, entityId: string, online: boolean) {
  const {
    mode,
    generation,
    saved,
    setSaved,
    draft,
    setDraft,
    busy,
    setBusy,
    error,
    setError,
    status,
    setStatus,
    setReload
  } = useHardwareConfigDraft(projectId, entityId, online)
  const disabled = busy || !online
  const save = async (): Promise<void> => {
    if (saved === null || disabled) return
    const ticket = generation.current
    setError(null)
    setStatus(null)
    let document
    try {
      document = prepareHardwareConfig(draft, entityId, saved.config)
    } catch (failure) {
      setError(draftError(failure))
      return
    }
    setBusy(true)
    try {
      const result = await putEntityHardwareConfig(projectId, entityId, document, saved.version)
      if (ticket !== generation.current) return
      if (!validSaved(result, entityId)) {
        setError('Configuration identity changed. Reload the project.')
        return
      }
      setSaved(result)
      setDraft(configDraft(result.config))
      setStatus('Configuration saved.')
    } catch (failure) {
      if (ticket !== generation.current) return
      setError(saveError(failure))
    } finally {
      if (ticket === generation.current) setBusy(false)
    }
  }
  return { mode, saved, draft, setDraft, error, status, setReload, disabled, save }
}

export function HardwareConfigPanel({
  projectId,
  entityId,
  online
}: {
  projectId: string
  entityId: string
  online: boolean
}): React.JSX.Element {
  const { mode, saved, draft, setDraft, error, status, setReload, disabled, save } =
    useHardwareConfigEditor(projectId, entityId, online)
  return (
    <section
      aria-label="Entity hardware configuration"
      onPointerDown={(event) => event.stopPropagation()}
      onWheel={(event) => event.stopPropagation()}
    >
      <h3>Hardware configuration</h3>
      {mode === 'Guide' && (
        <p>
          Edit the shared configuration below. Changed fields are attributed to you. Save checks the
          current version; private files are linked separately on this computer.
        </p>
      )}
      {!online && <p role="status">Connect to load configuration.</p>}
      <EmptyConfig saved={saved} />
      {error && <p role="alert">{error}</p>}
      {status && <p role="status">{status}</p>}
      {saved !== null && (
        <label>
          Configuration document
          <textarea
            aria-label="Hardware configuration"
            value={draft}
            maxLength={65536}
            spellCheck={false}
            disabled={disabled}
            onChange={(event) => setDraft(event.target.value)}
            style={{ width: '100%', minHeight: 160, fontFamily: 'var(--font-mono)' }}
          />
        </label>
      )}
      <div>
        <button disabled={disabled || saved === null} onClick={() => void save()}>
          Save configuration
        </button>{' '}
        <button disabled={disabled} onClick={() => setReload((value) => value + 1)}>
          Reload configuration
        </button>
      </div>
      {saved !== null && (
        <HardwareSourcesPanel
          projectId={projectId}
          mode={mode}
          sourceRefs={hardwareSourceRefs(saved.config)}
        />
      )}
    </section>
  )
}

function draftError(failure: unknown): string {
  return failure instanceof Error ? failure.message : 'Check the configuration.'
}
function validSaved(
  result: EntityHardwareConfigOut,
  entityId: string
): result is EntityHardwareConfigOut & { config: NonNullable<EntityHardwareConfigOut['config']> } {
  return result.entity_id === entityId && result.config?.entity_id === entityId
}
function saveError(failure: unknown): string {
  return failure instanceof ApiError && failure.status === 409
    ? 'Configuration changed. Your draft is retained; reload to review the current version before retrying.'
    : 'Configuration could not be saved. Check the fields and project access.'
}

function EmptyConfig({
  saved
}: {
  saved: EntityHardwareConfigOut | null
}): React.JSX.Element | null {
  return saved?.config === null ? (
    <p>No saved configuration. Saving creates one for this entity.</p>
  ) : null
}
