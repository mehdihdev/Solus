// SOLUSDEV-235 / EXT-12 — the rail icon. The ONLY place extension-authored
// markup is placed into the host DOM, and it is placed only after `reduceSvg`:
// `dangerouslySetInnerHTML` receives the reducer's output or nothing. Colours
// are `currentColor`, so the icon follows the rail's text colour and theme.
import { useMemo } from 'react'
import { reduceSvg } from './svgReduce'

export interface ExtensionIconProps {
  /** The icon file's text (from the registry's sanitized asset or a dev folder). */
  readonly svg: string | null | undefined
  readonly size?: number
  readonly className?: string
  /** Accessible name; without one the icon is decorative. */
  readonly label?: string
}

const DEFAULT_SIZE = 16

export function ExtensionIcon({
  svg,
  size = DEFAULT_SIZE,
  className = '',
  label
}: ExtensionIconProps): React.JSX.Element {
  const reduced = useMemo(() => (svg ? reduceSvg(svg) : null), [svg])
  const style = { width: size, height: size }
  if (reduced === null) {
    // Unacceptable or missing icon → a neutral tile, never the original bytes.
    return (
      <span
        aria-hidden="true"
        data-testid="extension-icon-fallback"
        className={`inline-block rounded-sm bg-sur2 ${className}`}
        style={style}
      />
    )
  }
  return (
    <span
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : 'true'}
      data-testid="extension-icon"
      className={`inline-flex text-current [&>svg]:h-full [&>svg]:w-full ${className}`}
      style={style}
      dangerouslySetInnerHTML={{ __html: reduced }}
    />
  )
}
