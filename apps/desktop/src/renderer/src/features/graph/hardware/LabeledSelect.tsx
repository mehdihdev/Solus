// A labelled <select> in the Add › Hardware input style, shared by every surface
// that picks a robot or a category.
import { FIELD_CONTROL_STYLE, FIELD_LABEL_STYLE } from './hardware.constants'

export function LabeledSelect<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled
}: {
  label: string
  value: T
  options: readonly { value: T; label: string }[]
  onChange: (value: T) => void
  disabled?: boolean
}): React.JSX.Element {
  return (
    <label style={FIELD_LABEL_STYLE}>
      {label}
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as T)}
        style={FIELD_CONTROL_STYLE}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}
