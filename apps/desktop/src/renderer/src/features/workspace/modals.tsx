// Shared workspace modals (extracted from HomeScreen so Home and Team reuse one
// implementation — DRY). ModalShell provides the dim backdrop + centered card;
// NameModal is the generic single-field create/rename dialog; JoinTeamModal
// redeems an invite token; DeleteConfirmModal is the destructive confirm.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'

/** Shared modal chrome: dim backdrop, centered card, click-out to close.
 *  Entrance motion via .modal-backdrop-in/.modal-card-in (main.css). */
export function ModalShell({
  onClose,
  width = 360,
  children
}: {
  onClose: () => void
  /** Card width; the default fits the single-field dialogs. */
  width?: number
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <div
      className="modal-backdrop-in"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.55)',
        zIndex: 70,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }}
      onClick={onClose}
    >
      <div className="modal-card-in" onClick={(e) => e.stopPropagation()}>
        <Card pad={24} style={{ width, boxShadow: '0 18px 60px rgba(0,0,0,0.5)' }}>
          {children}
        </Card>
      </div>
    </div>
  )
}

export const MODAL_INPUT_STYLE: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  marginTop: 16,
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '10px 12px',
  fontSize: 13,
  fontFamily: 'var(--font-ui)',
  outline: 'none'
}

export function NameModal({
  title,
  label,
  submitLabel = 'Create',
  initial = '',
  errorText = 'Something went wrong. Please try again.',
  onClose,
  onSubmit
}: {
  title: string
  label: string
  submitLabel?: string
  initial?: string
  errorText?: string
  onClose: () => void
  /** Resolve true on success (modal closes) or false to keep it open with an error. */
  onSubmit: (name: string) => Promise<boolean>
}): React.JSX.Element {
  const [name, setName] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const submit = async (): Promise<void> => {
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    const ok = await onSubmit(name.trim())
    if (ok) {
      onClose()
      return
    }
    setBusy(false)
    setError(errorText)
  }
  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>{title}</div>
      <input
        aria-label={label}
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder={label}
        autoFocus
        onKeyDown={(e) => e.key === 'Enter' && void submit()}
        style={MODAL_INPUT_STYLE}
      />
      {error && <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="primary" size="sm" onClick={() => void submit()}>
          {busy ? <Spinner size={11} color="var(--acc-ink)" /> : submitLabel}
        </Button>
      </div>
    </ModalShell>
  )
}

export function JoinTeamModal({
  onClose,
  onJoin
}: {
  onClose: () => void
  /** Resolve truthy on success (modal closes) or falsy to show the error. */
  onJoin: (token: string) => Promise<unknown>
}): React.JSX.Element {
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (): Promise<void> => {
    if (!token.trim()) return
    setBusy(true)
    setError(null)
    const joined = await onJoin(token.trim())
    setBusy(false)
    if (!joined) {
      setError("Couldn't join with that token. It may be invalid, expired, or for another email.")
      return
    }
    onClose()
  }

  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Join a team</div>
      <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 4, lineHeight: 1.5 }}>
        Paste the one-time invite token a teammate shared with you.
      </div>
      <input
        aria-label="Invite token"
        value={token}
        onChange={(e) => setToken(e.target.value)}
        placeholder="invite token"
        autoFocus
        onKeyDown={(e) => e.key === 'Enter' && void submit()}
        style={{ ...MODAL_INPUT_STYLE, fontFamily: 'var(--font-mono)' }}
      />
      {error && <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="primary" size="sm" onClick={() => void submit()}>
          {busy ? <Spinner size={11} color="var(--acc-ink)" /> : 'Join'}
        </Button>
      </div>
    </ModalShell>
  )
}

export function DeleteConfirmModal({
  name,
  onClose,
  onConfirm
}: {
  name: string
  onClose: () => void
  /** Resolve true on success (modal closes) or false to keep it open with an error. */
  onConfirm: () => Promise<boolean>
}): React.JSX.Element {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const confirm = async (): Promise<void> => {
    setBusy(true)
    setError(null)
    const ok = await onConfirm()
    if (ok) {
      onClose()
      return
    }
    setBusy(false)
    setError("Couldn't delete this project. Check your access and try again.")
  }
  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Delete project</div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 }}>
        Permanently delete <strong style={{ color: 'var(--tx)' }}>{name}</strong> and its graph.
        This cannot be undone.
      </div>
      {error && <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 18, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="danger" size="sm" onClick={() => void confirm()}>
          {busy ? <Spinner size={11} /> : 'Delete project'}
        </Button>
      </div>
    </ModalShell>
  )
}
