import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { SOLUS_SUBSECTIONS, type SolusSection } from '../../lib/api/resources'
import type { ComposerKind, ComposerSubmit } from './solusActions'
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

/** Where a new entry lands inside a section with fixed subsections (resources.ts). */
function SubsectionPicker({
  options,
  value,
  onChange
}: {
  options: readonly string[]
  value: string | undefined
  onChange: (next: string) => void
}): React.JSX.Element {
  return (
    <select
      aria-label="Subsection"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{
        marginRight: 'auto',
        background: 'var(--sur)',
        color: 'var(--tx)',
        border: '1px solid var(--bd)',
        borderRadius: 3,
        padding: '3px 6px',
        fontSize: 11,
        fontFamily: 'var(--font-ui)'
      }}
    >
      {options.map((option) => (
        <option key={option} value={option}>
          {option}
        </option>
      ))}
    </select>
  )
}

export function SolusComposer({
  kind,
  initial,
  section,
  subsection,
  onCancel,
  onSubmit
}: {
  kind: ComposerKind
  initial: string
  /** The target section: a new entry gets a subsection picker when it has fixed ones. */
  section?: SolusSection
  /** Preselected when the composer opened on a subsection node. */
  subsection?: string | null
  onCancel: () => void
  onSubmit: ComposerSubmit
}): React.JSX.Element {
  const [draft, setDraft] = useState(initial)
  const [busy, setBusy] = useState(false)
  // Editing changes text only (PATCH); only new entries pick where they land.
  const options = section && kind !== 'edit' ? SOLUS_SUBSECTIONS[section] : []
  const [picked, setPicked] = useState<string | undefined>(subsection ?? options[0])
  const send = async (): Promise<void> => {
    setBusy(true)
    try {
      await onSubmit(draft.trim(), kind === 'edit' ? undefined : picked)
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
        {options.length > 0 && (
          <SubsectionPicker options={options} value={picked} onChange={setPicked} />
        )}
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
