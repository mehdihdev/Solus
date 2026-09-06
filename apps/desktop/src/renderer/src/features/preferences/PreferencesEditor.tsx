// SOLUSDEV-244 / HOME H3: the editor half of the "How you engineer" card —
// one labelled textarea per section plus notes, a character counter on each
// (the cap is what bounds the prompt), Save / Cancel. Pure: draft in, draft out.
import { PREFERENCE_SECTIONS, type EngineeringPreferences } from '@solus/shared-types'
import { useId, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { FREE_TEXT_COPY, SECTION_COPY, type SectionCopy } from './preferences.constants'

const TEXTAREA_STYLE: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 4,
  padding: '8px 10px',
  fontSize: 11.5,
  fontFamily: 'var(--font-ui)',
  resize: 'vertical',
  outline: 'none',
  marginTop: 4
}

interface SectionInputProps {
  copy: SectionCopy
  value: string
  cap: number
  rows: number
  onChange: (value: string) => void
}

function SectionInput({ copy, value, cap, rows, onChange }: SectionInputProps): React.JSX.Element {
  const id = useId()
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <label htmlFor={id}>
          <Mono size={9.5}>{copy.label}</Mono>
        </label>
        <Mono size={9} style={{ color: value.length >= cap ? 'var(--warn)' : 'var(--mut)' }}>
          {value.length} / {cap}
        </Mono>
      </div>
      <textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        maxLength={cap}
        rows={rows}
        placeholder={copy.placeholder}
        style={TEXTAREA_STYLE}
      />
    </div>
  )
}

interface PreferencesEditorProps {
  initial: EngineeringPreferences
  fieldCap: number
  freeTextCap: number
  failed: boolean
  onCancel: () => void
  onSave: (draft: EngineeringPreferences) => void
}

export function PreferencesEditor({
  initial,
  fieldCap,
  freeTextCap,
  failed,
  onCancel,
  onSave
}: PreferencesEditorProps): React.JSX.Element {
  const [draft, setDraft] = useState<EngineeringPreferences>(initial)
  const patch = (key: keyof EngineeringPreferences, value: string): void =>
    setDraft((d) => ({ ...d, [key]: value }))
  return (
    <div>
      {PREFERENCE_SECTIONS.map((key) => (
        <SectionInput
          key={key}
          copy={SECTION_COPY[key]}
          value={draft[key]}
          cap={fieldCap}
          rows={2}
          onChange={(value) => patch(key, value)}
        />
      ))}
      <SectionInput
        copy={FREE_TEXT_COPY}
        value={draft.freeText}
        cap={freeTextCap}
        rows={4}
        onChange={(value) => patch('freeText', value)}
      />
      {failed && (
        <div role="alert" style={{ fontSize: 10.5, color: 'var(--err)', marginTop: 6 }}>
          Couldn&apos;t save your conventions — try again.
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', marginTop: 10 }}>
        <Button kind="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button kind="primary" size="sm" onClick={() => onSave(draft)}>
          Save
        </Button>
      </div>
    </div>
  )
}
