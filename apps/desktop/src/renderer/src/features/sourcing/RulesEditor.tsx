// SOLUSDEV-246 (STORE ST5) — the project's compliance / style rules, edited
// as typed fields. The server layers these over the repo's `[ext.sourcing]`
// table; what comes back is the effective set.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import type { SourcingRulesApi } from '../../lib/api/resources.sourcing'
import { excludedFrom } from './sourcingLogic'

const INPUT: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '6px 9px',
  fontSize: 12,
  fontFamily: 'var(--font-ui)',
  marginTop: 4
}

const list = (raw: string): string[] =>
  raw
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

export function RulesEditor({
  rules,
  onSave,
  onClose
}: {
  rules: SourcingRulesApi
  onSave: (rules: SourcingRulesApi) => Promise<boolean>
  onClose: () => void
}): React.JSX.Element {
  const [excluded, setExcluded] = useState(
    rules.excluded_suppliers.map((e) => `${e.name}: ${e.reason}`).join('; ')
  )
  const [certs, setCerts] = useState(rules.required_certifications.join(', '))
  const [voltage, setVoltage] = useState(
    rules.max_voltage_v === null ? '' : String(rules.max_voltage_v)
  )
  const [protocols, setProtocols] = useState(rules.allowed_protocols.join(', '))
  const [preferred, setPreferred] = useState(rules.preferred_suppliers.join(', '))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const save = async (): Promise<void> => {
    const maxVoltage = voltage.trim() === '' ? null : Number(voltage)
    if (maxVoltage !== null && (!Number.isFinite(maxVoltage) || maxVoltage < 0)) {
      setError('Max voltage must be a number of volts.')
      return
    }
    setBusy(true)
    const ok = await onSave({
      excluded_suppliers: excludedFrom(excluded),
      required_certifications: list(certs),
      max_voltage_v: maxVoltage,
      allowed_protocols: list(protocols),
      preferred_suppliers: list(preferred)
    })
    setBusy(false)
    if (ok) onClose()
    else setError("Couldn't save the rules.")
  }

  return (
    <div data-testid="sourcing-rules-editor" style={{ marginTop: 8 }}>
      {ruleField(
        'Excluded suppliers',
        excluded,
        setExcluded,
        'name: reason; name: reason — the reason is what an excluded candidate shows.'
      )}
      {ruleField('Required certifications', certs, setCerts, 'Comma-separated, e.g. RoHS, CE.')}
      {ruleField('Max voltage (V)', voltage, setVoltage, 'Candidates above it are excluded.')}
      {ruleField(
        'Allowed protocols',
        protocols,
        setProtocols,
        'Comma-separated; empty allows any.'
      )}
      {ruleField('Preferred suppliers', preferred, setPreferred, 'Ranked first, never excluded.')}
      {error && (
        <div role="alert" style={{ fontSize: 12, color: 'var(--warn)', marginTop: 8 }}>
          {error}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="primary" size="sm" disabled={busy} onClick={() => void save()}>
          {busy ? 'Saving…' : 'Save rules'}
        </Button>
      </div>
    </div>
  )
}

function ruleField(
  label: string,
  value: string,
  set: (v: string) => void,
  hint: string
): React.JSX.Element {
  return (
    <label style={{ display: 'block', marginTop: 10 }}>
      <Mono size={9}>{label}</Mono>
      <input aria-label={label} value={value} onChange={(e) => set(e.target.value)} style={INPUT} />
      <div style={{ fontSize: 10.5, color: 'var(--mut)', marginTop: 2 }}>{hint}</div>
    </label>
  )
}
