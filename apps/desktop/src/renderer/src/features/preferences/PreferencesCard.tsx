// SOLUSDEV-244 / HOME H3: "How you engineer" — the one part of ~/.solus the
// user owns. A DOCUMENT they write (five short sections plus notes), not a
// settings screen: no toggles. SOL reads it on every turn, above the shipped
// engineering references and below a project's own .solus. View → Edit →
// Save (optimistic, revert-on-failure); honest read-only / unavailable states.
import {
  PREFERENCES_FIELD_CAP,
  PREFERENCES_FREE_TEXT_CAP,
  PREFERENCE_SECTIONS,
  isEmptyPreferences,
  type EngineeringPreferences
} from '@solus/shared-types'
import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { FREE_TEXT_COPY, SECTION_COPY } from './preferences.constants'
import { PreferencesEditor } from './PreferencesEditor'
import { usePreferencesStore } from './preferencesStore'

const INTRO =
  'Your conventions — code style, mechanical and electrical design, documentation, units. ' +
  'SOL follows these on every turn and says when one changed its answer.'
/** Stated on the card, always: the file is one per machine (ADR-034), so a
 *  person cannot consent to sharing they were never told about. */
const SHARED_NOTE = 'Stored on this computer and shared by everyone who signs in here.'

function SectionView({ label, text }: { label: string; text: string }): React.JSX.Element {
  return (
    <div style={{ marginTop: 8 }}>
      <Mono size={9.5}>{label}</Mono>
      <div style={{ fontSize: 11.5, lineHeight: 1.5, whiteSpace: 'pre-wrap', marginTop: 2 }}>
        {text}
      </div>
    </div>
  )
}

function DocumentView({ preferences }: { preferences: EngineeringPreferences }): React.JSX.Element {
  if (isEmptyPreferences(preferences)) {
    return (
      <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 6, lineHeight: 1.5 }}>
        {INTRO}
      </div>
    )
  }
  return (
    <>
      {PREFERENCE_SECTIONS.filter((key) => preferences[key].trim()).map((key) => (
        <SectionView key={key} label={SECTION_COPY[key].label} text={preferences[key]} />
      ))}
      {preferences.freeText.trim() && (
        <SectionView label={FREE_TEXT_COPY.label} text={preferences.freeText} />
      )}
    </>
  )
}

function Notice({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 6, lineHeight: 1.5 }}>
      {children}
    </div>
  )
}

function StatusNotice({
  status,
  readOnly
}: {
  status: string
  readOnly: boolean
}): React.JSX.Element | null {
  if (status === 'unavailable') {
    return (
      <Notice>Your conventions live in ~/.solus and are edited in the Solus desktop app.</Notice>
    )
  }
  if (status === 'ready' && readOnly) {
    return (
      <Notice>
        This file was written by a newer version of Solus. It is shown here but not editable until
        you update.
      </Notice>
    )
  }
  return null
}

export function PreferencesCard(): React.JSX.Element {
  const { preferences, status, readOnly, load, save } = usePreferencesStore()
  const [editing, setEditing] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    void load()
  }, [load])

  const submit = async (draft: EngineeringPreferences): Promise<void> => {
    const ok = await save(draft)
    setFailed(!ok)
    if (ok) setEditing(false)
  }
  const beginEdit = (): void => {
    setFailed(false)
    setEditing(true)
  }

  const canEdit = status === 'ready' && !readOnly && !editing
  return (
    <Card pad={16} aria-label="How you engineer">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Mono size={10}>HOW YOU ENGINEER</Mono>
        {canEdit && (
          <Button kind="soft" size="sm" onClick={beginEdit}>
            {isEmptyPreferences(preferences) ? '+ Add' : 'Edit'}
          </Button>
        )}
      </div>
      <StatusNotice status={status} readOnly={readOnly} />
      {status === 'ready' && !editing && <DocumentView preferences={preferences} />}
      {status === 'ready' && (
        <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 8 }}>{SHARED_NOTE}</div>
      )}
      {editing && (
        <PreferencesEditor
          initial={preferences}
          fieldCap={PREFERENCES_FIELD_CAP}
          freeTextCap={PREFERENCES_FREE_TEXT_CAP}
          failed={failed}
          onCancel={() => setEditing(false)}
          onSave={(draft) => void submit(draft)}
        />
      )}
    </Card>
  )
}
