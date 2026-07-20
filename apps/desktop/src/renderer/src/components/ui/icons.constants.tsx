// Geometric line icons, ported from SI in TestDesign/app/util.jsx.
// Each icon renders an inline SVG using stroke/fill="currentColor" so it inherits
// text color. Sized via the `size` prop (square).
import type { CSSProperties, JSX } from 'react'

export interface IconProps {
  size?: number
  className?: string
  style?: CSSProperties
  title?: string
}

type IconComponent = (props: IconProps) => JSX.Element

function makeIcon(viewBox: string, inner: string, defaultSize = 17): IconComponent {
  return function Icon({ size = defaultSize, className, style, title }: IconProps) {
    return (
      <svg
        width={size}
        height={size}
        viewBox={viewBox}
        className={className}
        style={style}
        role={title ? 'img' : undefined}
        aria-label={title}
        aria-hidden={title ? undefined : true}
        // `inner` is a compile-time constant icon path defined in this module —
        // never user-controlled. No dynamic interpolation is injected here.
        dangerouslySetInnerHTML={{ __html: inner }}
      />
    )
  }
}

export const Icons = {
  graph: makeIcon(
    '0 0 17 17',
    '<circle cx="4" cy="4" r="2.4" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="13" cy="6" r="2.4" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="7" cy="13" r="2.4" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M6 5l4.8.8M5.8 11.2L11.8 8" stroke="currentColor" stroke-width="1.2"/>'
  ),
  check: makeIcon(
    '0 0 17 17',
    '<path d="M3 9l4 4 7-8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
  ),
  warn: makeIcon(
    '0 0 17 17',
    '<path d="M8.5 2.2L15.6 14H1.4L8.5 2.2z" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M8.5 7v3.2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="8.5" cy="12.2" r="0.8" fill="currentColor"/>'
  ),
  x: makeIcon(
    '0 0 17 17',
    '<path d="M4 4l9 9M13 4l-9 9" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>'
  ),
  arrowR: makeIcon(
    '0 0 17 17',
    '<path d="M3 8.5h10M9.5 4.5l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
  ),
  arrowL: makeIcon(
    '0 0 17 17',
    '<path d="M14 8.5H4M7.5 4.5l-4 4 4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
  ),
  github: makeIcon(
    '0 0 17 17',
    '<circle cx="8.5" cy="8.5" r="6.5" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M6 14.5v-2.2c0-.6.2-1 .5-1.3-1.7-.3-3-1.1-3-3.1 0-.9.3-1.5.8-2-.1-.3-.3-1.1.1-2 0 0 .7-.2 2.1.8a6.7 6.7 0 013.1 0c1.4-1 2.1-.8 2.1-.8.4.9.2 1.7.1 2 .5.5.8 1.1.8 2 0 2-1.3 2.8-3 3.1.3.3.5.8.5 1.4v2.1" fill="none" stroke="currentColor" stroke-width="1.1"/>'
  ),
  mail: makeIcon(
    '0 0 17 17',
    '<rect x="2" y="3.5" width="13" height="10" rx="1.2" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M2.4 4.5l6.1 4.2 6.1-4.2" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>'
  ),
  link: makeIcon(
    '0 0 17 17',
    '<path d="M7 10l3-3M5.5 8L3.8 9.7a2.6 2.6 0 003.6 3.6L9 11.6M11.5 9l1.7-1.7a2.6 2.6 0 00-3.6-3.6L8 5.4" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>'
  ),
  bench: makeIcon(
    '0 0 17 17',
    '<path d="M1 9h3l2-5 3 9 2-4h5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
  ),
  sol: makeIcon(
    '0 0 17 17',
    '<circle cx="8.5" cy="8.5" r="4" fill="currentColor" opacity="0.85"/><circle cx="8.5" cy="8.5" r="7" fill="none" stroke="currentColor" stroke-width="1" opacity="0.4"/>'
  ),
  team: makeIcon(
    '0 0 17 17',
    '<circle cx="6" cy="6" r="2.6" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="11.5" cy="7.5" r="2" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M2 14c.5-2.5 2-3.8 4-3.8s3.5 1.3 4 3.8M10 13.5c.3-1.8 1.4-2.8 2.8-2.8 1 0 1.9.5 2.4 1.6" fill="none" stroke="currentColor" stroke-width="1.3"/>'
  ),
  gear: makeIcon(
    '0 0 17 17',
    '<circle cx="8.5" cy="8.5" r="2.5" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="8.5" cy="8.5" r="5.8" fill="none" stroke="currentColor" stroke-width="1.4" stroke-dasharray="2.8 2.4"/>'
  ),
  bell: makeIcon(
    '0 0 17 17',
    '<path d="M8.5 2a4.2 4.2 0 014.2 4.2c0 3 .9 4.3 1.8 5H2.5c.9-.7 1.8-2 1.8-5A4.2 4.2 0 018.5 2zM7 13.5a1.6 1.6 0 003 0" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>'
  ),
  plus: makeIcon(
    '0 0 17 17',
    '<path d="M8.5 3v11M3 8.5h11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>'
  ),
  file: makeIcon(
    '0 0 17 17',
    '<path d="M4 1.8h6l3.2 3.2v10.2H4V1.8z" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/><path d="M10 1.8V5h3.2" fill="none" stroke="currentColor" stroke-width="1.2"/>'
  ),
  chip2: makeIcon(
    '0 0 17 17',
    '<rect x="4.5" y="4.5" width="8" height="8" rx="1" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M6.5 4.5v-2.3M10.5 4.5V2.2M6.5 14.8v-2.3M10.5 14.8v-2.3M4.5 6.5H2.2M4.5 10.5H2.2M14.8 6.5h-2.3M14.8 10.5h-2.3" stroke="currentColor" stroke-width="1.1"/>'
  ),
  play: makeIcon('0 0 17 17', '<path d="M5 3.5l8 5-8 5v-10z" fill="currentColor"/>'),
  pause: makeIcon(
    '0 0 17 17',
    '<path d="M5.5 3.5v10M11.5 3.5v10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'
  ),
  search: makeIcon(
    '0 0 17 17',
    '<circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M10.5 10.5L15 15" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>'
  ),
  spark: makeIcon(
    '0 0 17 17',
    '<path d="M9.5 1.5L4 9.5h4L7 15.5l6-8.5H8.5l1-5.5z" fill="currentColor"/>'
  ),
  box: makeIcon(
    '0 0 17 17',
    '<path d="M8.5 1.8l6 3.2v7l-6 3.2-6-3.2v-7l6-3.2z" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/><path d="M2.5 5l6 3.2 6-3.2M8.5 8.2v7" fill="none" stroke="currentColor" stroke-width="1.1"/>'
  ),
  card: makeIcon(
    '0 0 17 17',
    '<rect x="1.8" y="3.5" width="13.4" height="10" rx="1.4" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M1.8 6.8h13.4" stroke="currentColor" stroke-width="1.3"/><path d="M4 11h3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>'
  )
} as const

export type IconName = keyof typeof Icons
