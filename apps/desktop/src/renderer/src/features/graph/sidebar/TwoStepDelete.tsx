// The one inline destructive confirm on the Workspace (SOLUSDEV-250 P4): a modal-free
// two-step that still shows the concrete action before anything runs (CLAUDE.md §7).
// Controlled — the owner decides when it is armed, so a context menu can arm it too.
import { useState } from 'react'
import { Button } from '../../../components/ui/Button'

export interface TwoStepDeleteProps {
  /** The verb + noun on the confirm button, e.g. "Delete robot". */
  label: string
  /** The concrete line shown once armed: what goes, what stays. */
  detail: string
  armed: boolean
  busy?: boolean
  error?: string | null
  onArm: () => void
  onDisarm: () => void
  /** Resolves true when the target is gone; false keeps the step open. */
  onConfirm: () => Promise<boolean>
}

export function TwoStepDelete({
  label,
  detail,
  armed,
  busy = false,
  error = null,
  onArm,
  onDisarm,
  onConfirm
}: TwoStepDeleteProps): React.JSX.Element {
  const [pending, setPending] = useState(false)
  const disabled = busy || pending
  const confirm = async (): Promise<void> => {
    if (disabled) return
    setPending(true)
    try {
      if (await onConfirm()) onDisarm()
    } finally {
      setPending(false)
    }
  }
  if (!armed)
    return (
      <Button kind="bare" size="sm" disabled={disabled} onClick={onArm}>
        {label}…
      </Button>
    )
  return (
    <div className="two-step-delete">
      <p>{detail}</p>
      {error && <p role="alert">{error}</p>}
      <div className="two-step-delete-actions">
        <Button kind="danger" size="sm" disabled={disabled} onClick={() => void confirm()}>
          {label}
        </Button>
        <Button kind="ghost" size="sm" disabled={disabled} onClick={onDisarm}>
          Keep
        </Button>
      </div>
    </div>
  )
}
