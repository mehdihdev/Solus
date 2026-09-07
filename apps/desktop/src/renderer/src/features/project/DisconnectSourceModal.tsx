// Confirmed disconnect for one project source (SOLUSDEV-164), shared by the
// Sources page and Home's connected-accounts rows: it stops syncing and keeps
// the graph entities the source contributed — the copy says exactly that.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { ModalShell } from '../workspace/modals'

export function DisconnectSourceModal({
  name,
  onClose,
  onConfirm
}: {
  name: string
  onClose: () => void
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
    setError("Couldn't disconnect this source. Check your access and try again.")
  }
  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Disconnect {name}?</div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 }}>
        Stops syncing this tool. Solus keeps the entities it has already contributed to your graph,
        and you can reconnect it anytime.
      </div>
      {error && <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 18, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="danger" size="sm" disabled={busy} onClick={() => void confirm()}>
          {busy ? 'Disconnecting…' : 'Disconnect'}
        </Button>
      </div>
    </ModalShell>
  )
}
