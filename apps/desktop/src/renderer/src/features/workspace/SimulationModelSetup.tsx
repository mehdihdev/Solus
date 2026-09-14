import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { createSimulationModel } from '../../lib/api/resources.simulation'
import { useSettingsStore } from '../../store/settingsStore'

export function SimulationModelSetup({ projectId }: { projectId: string }): React.JSX.Element {
  return <ProjectModelSetup key={projectId} projectId={projectId} />
}

function ProjectModelSetup({ projectId }: { projectId: string }): React.JSX.Element {
  const [busy, setBusy] = useState(false)
  const [modelId, setModelId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pending = useRef(false)
  const active = useRef(true)
  const mode = useSettingsStore((state) => state.solMode)
  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])
  const create = async (): Promise<void> => {
    if (pending.current) return
    pending.current = true
    setBusy(true)
    setError(null)
    try {
      const result = await createSimulationModel(projectId)
      if (active.current) setModelId(result.model.id)
    } catch (reason) {
      if (active.current) setError(reason instanceof Error ? reason.message : 'Model setup failed.')
    } finally {
      pending.current = false
      if (active.current) setBusy(false)
    }
  }
  return (
    <section
      aria-label="Isaac Sim model setup"
      style={{ padding: 16, borderBottom: '1px solid var(--bd)' }}
    >
      <div style={{ fontWeight: 600 }}>Isaac Sim · SO-101 model</div>
      <p style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.5 }}>
        Add the pinned official SO-101 model to this project: eight links, six joints, one example
        jaw contact sensor and a bottle. The sensor and bottle are simulation examples, not measured
        hardware. This creates graph entities; simulator actions run through SOL approval.
      </p>
      {mode === 'Guide' && (
        <p style={{ fontSize: 12 }}>
          The graph gives SOL the model identities it needs to load and verify the scene.
        </p>
      )}
      <Button size="sm" disabled={busy} onClick={() => void create()}>
        {busy ? 'Adding model…' : 'Add SO-101 model'}
      </Button>
      {modelId && (
        <p role="status" style={{ fontSize: 12, overflowWrap: 'anywhere' }}>
          Graph model ready: {modelId}. Ask SOL to probe Isaac, then start and load this model.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  )
}
