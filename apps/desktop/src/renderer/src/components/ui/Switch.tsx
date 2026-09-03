// On/off switch primitive (SOLUSDEV-235). A real button with role="switch" so
// it is keyboard- and screen-reader-operable; tokens only, no hardcoded color.
interface SwitchProps {
  checked: boolean
  onChange: (checked: boolean) => void
  ariaLabel: string
  disabled?: boolean
}

const TRACK_W = 34
const TRACK_H = 18
const KNOB = 12
const KNOB_INSET = 2

export function Switch({
  checked,
  onChange,
  ariaLabel,
  disabled = false
}: SwitchProps): React.JSX.Element {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={disabled ? undefined : 'interactive'}
      style={{
        position: 'relative',
        width: TRACK_W,
        height: TRACK_H,
        padding: 0,
        borderRadius: 99,
        border: '1px solid var(--bd)',
        background: checked ? 'var(--acc)' : 'var(--sur2)',
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        transition: 'background 0.12s'
      }}
    >
      <span
        style={{
          position: 'absolute',
          top: KNOB_INSET,
          left: checked ? TRACK_W - KNOB - KNOB_INSET - 2 : KNOB_INSET,
          width: KNOB,
          height: KNOB,
          borderRadius: 99,
          background: checked ? 'var(--acc-ink)' : 'var(--mut)',
          transition: 'left 0.12s'
        }}
      />
    </button>
  )
}
