import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { updateSource, type Source } from '../../lib/api/resources'
import { useSettingsStore } from '../../store/settingsStore'
import { ModalShell, MODAL_INPUT_STYLE } from '../workspace/modals'

interface BindingProps {
  projectId: string
  source: Source
  onSaved: () => void
}

function invalidPath(path: string, provider: string): boolean {
  return (
    !path ||
    path.length > 512 ||
    path.trim() !== path ||
    /[\\:]/.test(path) ||
    [...path].some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127) ||
    path.split('/').some((part) => !part || part === '.' || part === '..') ||
    (provider === 'kicad' && !path.endsWith('.kicad_pro'))
  )
}

/** Exposed by the connector's project_path capability; never a native registry write. */
export function LocalProjectBinding(props: BindingProps): React.JSX.Element {
  const [editing, setEditing] = useState(false)
  const [saved, setSaved] = useState(false)
  const linked =
    typeof props.source.config.project_path === 'string' && props.source.config.project_path
  const label = linked || saved ? 'Edit project link' : 'Link project file'
  return (
    <>
      <Button
        kind="ghost"
        size="sm"
        aria-label={`${label} for ${props.source.name}`}
        onClick={() => {
          setSaved(false)
          setEditing(true)
        }}
      >
        {label}
      </Button>
      {saved && (
        <span role="status" style={{ fontSize: 11, color: 'var(--ok)' }}>
          Project link saved
        </span>
      )}
      {editing && (
        <BindingForm
          {...props}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setSaved(true)
            setEditing(false)
            props.onSaved()
          }}
        />
      )}
    </>
  )
}

function BindingForm({
  projectId,
  source,
  onClose,
  onSaved
}: BindingProps & { onClose: () => void }): React.JSX.Element {
  const [path, setPath] = useState(
    typeof source.config.project_path === 'string' ? source.config.project_path : ''
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inFlight = useRef(false)
  const alive = useRef(true)
  const title = useId()
  const field = useId()
  const solMode = useSettingsStore((state) => state.solMode)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  const save = async (): Promise<void> => {
    if (inFlight.current) return
    if (invalidPath(path, source.type)) {
      setError(
        source.type === 'kicad'
          ? 'Enter a relative .kicad_pro path inside the linked local folder (maximum 512 characters).'
          : 'Enter a relative project file path inside the linked local folder (maximum 512 characters).'
      )
      return
    }
    inFlight.current = true
    setBusy(true)
    setError(null)
    try {
      await updateSource(projectId, source.id, { config: { project_path: path } })
      if (alive.current) onSaved()
    } catch {
      if (alive.current)
        setError('Could not save the project link. Check your access and try again.')
    } finally {
      inFlight.current = false
      if (alive.current) setBusy(false)
    }
  }
  return (
    <ModalShell
      onClose={() => {
        if (!inFlight.current) onClose()
      }}
      width={460}
    >
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby={title}
        onSubmit={(event) => {
          event.preventDefault()
          void save()
        }}
      >
        <BindingFields
          source={source}
          title={title}
          field={field}
          solMode={solMode}
          path={path}
          busy={busy}
          error={error}
          setPath={setPath}
          onClose={onClose}
        />
      </form>
    </ModalShell>
  )
}

interface BindingFieldsProps {
  source: Source
  title: string
  field: string
  solMode: string
  path: string
  busy: boolean
  error: string | null
  setPath: (value: string) => void
  onClose: () => void
}

function BindingFields({
  source,
  title,
  field,
  solMode,
  path,
  busy,
  error,
  setPath,
  onClose
}: BindingFieldsProps): React.JSX.Element {
  return (
    <>
      <h2 id={title} style={{ fontSize: 16, margin: 0 }}>
        Project file for {source.name}
      </h2>
      <p style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.55 }}>
        {solMode === 'Guide'
          ? 'Use the project file inside the local folder linked to this project. Enter its path from that folder, not its full computer path. The companion reads it when your design changes.'
          : 'Relative to this project’s linked local folder. Companion changes refresh the design.'}
        {source.type === 'kicad' && ' Choose the .kicad_pro project beside your schematic.'}
      </p>
      <label htmlFor={field} style={{ fontSize: 12 }}>
        Project file path
      </label>
      <input
        id={field}
        value={path}
        onChange={(event) => setPath(event.target.value)}
        disabled={busy}
        maxLength={512}
        style={{ ...MODAL_INPUT_STYLE, marginTop: 6 }}
        spellCheck={false}
      />
      <p style={{ fontSize: 11, color: 'var(--mut)' }}>
        Saving links the file; it does not verify an export or sync.
      </p>
      {error && (
        <div role="alert" style={{ fontSize: 12, color: 'var(--err)' }}>
          {error}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, marginTop: 18, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" disabled={busy} onClick={onClose}>
          Cancel
        </Button>
        <Button kind="primary" size="sm" type="submit" disabled={busy}>
          {busy ? 'Saving…' : 'Save project link'}
        </Button>
      </div>
    </>
  )
}
