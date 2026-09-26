import { useEffect, useRef, useState } from 'react'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../../graph/workspaceSession'
import { cadSources, bindCad, type CadSource } from './cadApi'
import type { SceneModel } from './types'
type Props = { projectId: string; model: SceneModel; onSaved: () => void }
export function CadBindings(props: Props): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  return (
    <Panel
      key={`${props.projectId}:${props.model.id}:${generation}`}
      {...props}
      generation={generation}
    />
  )
}
function Panel({
  projectId,
  model,
  onSaved,
  generation
}: Props & { generation: number }): React.JSX.Element {
  const [open, setOpen] = useState(false),
    [sources, setSources] = useState<CadSource[]>([])
  const [version, setVersion] = useState(model.version)
  const [selected, setSelected] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [saved, setSaved] = useState('')
  const alive = useRef(true),
    inFlight = useRef(false)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    void cadSources(projectId, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted && generation === workspaceSessionGeneration())
          setSources(value)
      })
      .catch(() => {
        if (!controller.signal.aborted) setError('CAD sources could not be loaded.')
      })
    return () => controller.abort()
  }, [projectId, open, generation])
  const review = (): void => {
    setVersion(model.version)
    setOpen(true)
    setSaved('')
    setError('')
    setSelected(
      Object.fromEntries(
        (model.cad_bindings ?? []).map((binding) => [binding.mesh_key, binding.source_entity_id])
      )
    )
  }
  const save = async (): Promise<void> => {
    if (inFlight.current || version !== model.version) return
    inFlight.current = true
    setBusy(true)
    setError('')
    try {
      const bindings = Object.entries(selected)
        .filter(([, id]) => id)
        .map(([mesh_key, source_entity_id]) => ({ mesh_key, source_entity_id }))
      const result = await bindCad(projectId, model.id, version, bindings)
      if (alive.current && generation === workspaceSessionGeneration()) {
        setSaved(
          bindings.length === 0 ? 'CAD links removed.' : `CAD refresh ${result.refresh_status}.`
        )
        setOpen(false)
        onSaved()
      }
    } catch {
      if (alive.current && generation === workspaceSessionGeneration())
        setError('CAD links could not be saved. Reload and review the current model.')
    } finally {
      inFlight.current = false
      if (alive.current) setBusy(false)
    }
  }
  const meshes = Object.keys(model.model.meshes ?? {})
  return (
    <section aria-label="CAD geometry links">
      <CadRefreshStatus model={model} />
      {meshes.length > 0 && (
        <button disabled={busy} onClick={review}>
          Link CAD geometry
        </button>
      )}
      {open && (
        <fieldset disabled={busy}>
          <legend>Choose the CAD source for each mesh</legend>
          <p>
            Successful CAD syncs update linked geometry. Joint structure and placement stay with
            this model.
          </p>
          {meshes.map((mesh) => (
            <label key={mesh}>
              {mesh}
              <select
                aria-label={`CAD source for ${mesh}`}
                value={selected[mesh] ?? ''}
                onChange={(event) => setSelected((old) => ({ ...old, [mesh]: event.target.value }))}
              >
                <option value="">No CAD link</option>
                {selected[mesh] && !sources.some((source) => source.id === selected[mesh]) && (
                  <option value={selected[mesh]} disabled>
                    Linked CAD source unavailable
                  </option>
                )}
                {sources.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.name} · {source.observed_microversion ?? 'Revision unknown'}
                  </option>
                ))}
              </select>
            </label>
          ))}
          {version !== model.version && (
            <p role="alert">Model changed. Reopen CAD links to review it.</p>
          )}
          <button disabled={busy || version !== model.version} onClick={() => void save()}>
            Confirm CAD links
          </button>
        </fieldset>
      )}
      {saved && <p role="status">{saved}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  )
}

function CadRefreshStatus({ model }: { model: SceneModel }): React.JSX.Element {
  return (
    <>
      {' '}
      {model.refresh_status && <p>CAD refresh: {model.refresh_status}</p>}
      {model.refresh_error && <p role="status">{model.refresh_error}</p>}
      {(model.cad_bindings ?? []).map((binding) => (
        <p key={binding.mesh_key}>
          {binding.mesh_key} · microversion {binding.observed_microversion ?? 'Pending'}
        </p>
      ))}
    </>
  )
}
