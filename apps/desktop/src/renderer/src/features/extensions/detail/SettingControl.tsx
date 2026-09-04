// SOLUSDEV-235 — one control per manifest `[[settings.fields]]` entry. The
// field's declared type picks the widget; the server re-validates every value
// against the same manifest (docs/api/extensions.md §6.3), so this is display
// and first-line validation only.
import { useEffect, useState } from 'react'
import type { SettingField } from '@solus/shared-types'
import { Switch } from '../../../components/ui/Switch'
import type { ExtensionSettingValue } from '../extension.types'

const INPUT_STYLE: React.CSSProperties = {
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '6px 10px',
  fontSize: 12,
  fontFamily: 'var(--font-ui)',
  outline: 'none'
}

interface ControlProps {
  field: SettingField
  value: ExtensionSettingValue | undefined
  disabled: boolean
  onChange: (value: ExtensionSettingValue) => void
}

export function SettingControl(props: ControlProps): React.JSX.Element {
  const { field, value, disabled, onChange } = props
  const style = { ...INPUT_STYLE, opacity: disabled ? 0.45 : 1 }
  switch (field.type) {
    case 'boolean':
      return (
        <Switch
          checked={value === true}
          disabled={disabled}
          ariaLabel={field.label}
          onChange={onChange}
        />
      )
    case 'select':
      return (
        <select
          aria-label={field.label}
          value={typeof value === 'string' ? value : ''}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          style={style}
        >
          {(field.options ?? []).map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      )
    case 'number':
      return <NumberControl {...props} style={{ ...style, width: 110 }} />
    default:
      return (
        <input
          type="text"
          aria-label={field.label}
          value={typeof value === 'string' ? value : ''}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          style={{ ...style, width: 180 }}
        />
      )
  }
}

/** Keeps the raw text while the user edits (an emptied field must not snap
 *  back to the old number), and reports only finite numbers upward. */
function NumberControl({
  field,
  value,
  disabled,
  onChange,
  style
}: ControlProps & { style: React.CSSProperties }): React.JSX.Element {
  const [text, setText] = useState(typeof value === 'number' ? String(value) : '')
  useEffect(() => {
    if (typeof value === 'number' && Number(text) !== value) setText(String(value))
    // Only an external change to `value` should overwrite what is being typed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])
  return (
    <input
      type="number"
      aria-label={field.label}
      value={text}
      min={field.min}
      max={field.max}
      disabled={disabled}
      onChange={(e) => {
        setText(e.target.value)
        const n = Number(e.target.value)
        if (e.target.value !== '' && Number.isFinite(n)) onChange(n)
      }}
      style={style}
    />
  )
}
