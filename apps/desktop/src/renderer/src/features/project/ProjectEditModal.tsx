// Edit-project modal (SOLUSDEV-164): rename and re-describe a project from its
// Overview hub. Mirrors the workspace NameModal contract (onSubmit resolves
// true to close, false to keep open with an error) but adds a description
// field. Reuses the shared modal chrome so Home/Team/Overview look identical.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'
import { ModalShell, MODAL_INPUT_STYLE } from '../workspace/modals'

export interface ProjectEditModalProps {
  initialName: string
  initialDescription: string
  onClose: () => void
  /** Resolve true on success (modal closes) or false to keep it open with an error. */
  onSubmit: (name: string, description: string) => Promise<boolean>
}

export function ProjectEditModal({
  initialName,
  initialDescription,
  onClose,
  onSubmit
}: ProjectEditModalProps): React.JSX.Element {
  const [name, setName] = useState(initialName)
  const [description, setDescription] = useState(initialDescription)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (): Promise<void> => {
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    const ok = await onSubmit(name.trim(), description.trim())
    if (ok) {
      onClose()
      return
    }
    setBusy(false)
    setError("Couldn't save your changes. Check your access and try again.")
  }

  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Edit project</div>
      <input
        aria-label="Project name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Project name"
        autoFocus
        onKeyDown={(e) => e.key === 'Enter' && void submit()}
        style={MODAL_INPUT_STYLE}
      />
      <textarea
        aria-label="Description"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="What is this robot? (optional)"
        rows={3}
        style={{ ...MODAL_INPUT_STYLE, resize: 'vertical', lineHeight: 1.5 }}
      />
      {error && <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="primary" size="sm" disabled={busy} onClick={() => void submit()}>
          {busy ? <Spinner size={11} color="var(--acc-ink)" /> : 'Save'}
        </Button>
      </div>
    </ModalShell>
  )
}
