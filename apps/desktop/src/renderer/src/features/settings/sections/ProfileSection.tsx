// Profile settings: display-name edit (PATCH /users/me) with inline validation
// and envelope errors. Email is read-only (identity comes from Supabase auth).
import { useState } from 'react'
import { Avatar } from '../../../components/ui/Avatar'
import { Button } from '../../../components/ui/Button'
import { displayName } from '../../workspace/useMe'
import { Section, InlineError } from '../settingsUi'
import type { SettingsData } from '../useSettingsData'

const inputStyle: React.CSSProperties = {
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '8px 10px',
  fontSize: 13,
  fontFamily: 'var(--font-ui)',
  outline: 'none',
  minWidth: 220
}

export function ProfileSection({ data }: { data: SettingsData }): React.JSX.Element {
  const { profile, errors, actions } = data
  const [name, setName] = useState(profile?.name ?? '')
  const [saving, setSaving] = useState(false)

  const email = profile?.email ?? ''
  const save = async (): Promise<void> => {
    setSaving(true)
    await actions.updateName(name)
    setSaving(false)
  }

  return (
    <Section id="profile" title="Profile" sub="Your identity across the team's shared graph.">
      <div style={{ display: 'flex', gap: 14, alignItems: 'center', marginBottom: 14 }}>
        <Avatar name={displayName(name, email)} size={42} />
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{displayName(name, email)}</div>
          <div style={{ fontSize: 11.5, color: 'var(--mut)' }}>{email}</div>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input
          aria-label="Display name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Your name"
          style={inputStyle}
        />
        <Button kind="ghost" size="sm" onClick={() => void save()} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </div>
      <InlineError message={errors.name} />
    </Section>
  )
}
