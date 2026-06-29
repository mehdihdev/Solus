// Labeled text input, ported from AuthField in TestDesign/app/auth.jsx.
import { useId } from 'react'
import { Mono } from './Mono'

interface FieldProps {
  label: string
  type?: 'text' | 'email' | 'password'
  value: string
  onChange: (value: string) => void
  placeholder?: string
  error?: string
  autoComplete?: string
  onSubmit?: () => void
}

export function Field({
  label,
  type = 'text',
  value,
  onChange,
  placeholder,
  error,
  autoComplete,
  onSubmit
}: FieldProps): React.JSX.Element {
  const id = useId()
  const errorId = `${id}-error`
  return (
    <div style={{ marginBottom: 14 }}>
      <label htmlFor={id} style={{ display: 'block', marginBottom: 6 }}>
        <Mono size={9.5}>{label}</Mono>
      </label>
      <input
        id={id}
        type={type}
        value={value}
        placeholder={placeholder}
        autoComplete={autoComplete}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && onSubmit) onSubmit()
        }}
        style={{
          width: '100%',
          boxSizing: 'border-box',
          background: 'var(--bg)',
          color: 'var(--tx)',
          border: `1px solid ${error ? 'var(--err)' : 'var(--bd)'}`,
          borderRadius: 3,
          padding: '10px 12px',
          fontSize: 13.5,
          fontFamily: 'var(--font-ui)',
          outline: 'none'
        }}
      />
      {error && (
        <span
          id={errorId}
          style={{ fontSize: 11, color: 'var(--err)', marginTop: 4, display: 'block' }}
        >
          {error}
        </span>
      )}
    </div>
  )
}
