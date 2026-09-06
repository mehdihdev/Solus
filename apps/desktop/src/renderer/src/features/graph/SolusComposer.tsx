import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import type { ComposerKind } from './solusActions'
const PLACEHOLDER: Readonly<Record<ComposerKind, string>> = {
  ask: "What should SOL find? e.g. 'FSAE EV rules on fusing'",
  type: 'Type it — plain text',
  edit: 'Edit the note'
}

const CONFIRM: Readonly<Record<ComposerKind, string>> = {
  ask: 'Ask SOL',
  type: 'Add',
  edit: 'Save'
}

export function SolusComposer({
  kind,
  initial,
  onCancel,
  onSubmit
}: {
  kind: ComposerKind
  initial: string
  onCancel: () => void
  onSubmit: (text: string) => Promise<void>
}): React.JSX.Element {
  const [draft, setDraft] = useState(initial)
  const [busy, setBusy] = useState(false)
  const send = async (): Promise<void> => {
    setBusy(true)
    try {
      await onSubmit(draft.trim())
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="solus-node-editor" style={{ padding: 4 }}>
      <textarea
        autoFocus
        value={draft}
        maxLength={4000}
        onChange={(e) => setDraft(e.target.value)}
        placeholder={PLACEHOLDER[kind]}
        style={{
          width: '100%',
          boxSizing: 'border-box',
          height: 56,
          background: 'var(--sur)',
          color: 'var(--tx)',
          border: '1px solid var(--acc)',
          borderRadius: 3,
          padding: '7px 9px',
          fontSize: 11.5,
          fontFamily: 'var(--font-ui)',
          resize: 'none',
          outline: 'none'
        }}
      />
      <div
        style={{
          display: 'flex',
          gap: 6,
          justifyContent: 'flex-end',
          alignItems: 'center',
          marginTop: 6
        }}
      >
        {draft.length > 3500 && <Mono size={8}>{draft.length} / 4000</Mono>}
        <Button kind="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          kind="primary"
          size="sm"
          disabled={busy || !draft.trim()}
          onClick={() => void send()}
        >
          {CONFIRM[kind]}
        </Button>
      </div>
    </div>
  )
}
