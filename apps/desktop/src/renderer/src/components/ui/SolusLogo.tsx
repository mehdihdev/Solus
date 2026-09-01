// The Solus brand logo (SOLUSDEV-233): the mark from assets/solus-logo.svg,
// inlined so its colors ride the runtime design tokens — it re-skins with the
// theme AND accent chosen in Settings (applyTheme sets the vars). The OS-level
// app icon (resources/icon.png) stays the static brand rendering on purpose.
// Geometry is verbatim from the asset; only the colors are tokenized:
//   tile      → --sur2 on a --bd hairline
//   connector → --acc
//   ringed nodes → --sur holes with --acc rings
//   solid nodes  → accent tinted toward --tx (lighter on dark themes,
//                  darker on light themes — same contrast direction as the mark)
// Used in brand positions — the shell rail's home button, the auth wordmark,
// Settings. The SOL page header and the floating mini-orb keep the SolOrb:
// the orb is SOL's presence, the logo is the product's.

interface SolusLogoProps {
  size?: number
}

const NODE_FILL = 'color-mix(in srgb, var(--acc) 70%, var(--tx))'

export function SolusLogo({ size = 24 }: SolusLogoProps): React.JSX.Element {
  return (
    <svg
      role="img"
      aria-label="Solus"
      width={size}
      height={size}
      viewBox="0 0 512 512"
      fill="none"
      style={{ display: 'block', flexShrink: 0 }}
    >
      <rect
        width="512"
        height="512"
        rx="112"
        style={{ fill: 'var(--sur2)', stroke: 'var(--bd)' }}
        strokeWidth="8"
      />
      <path
        d="M383.667 110.667L161.8 187.467L349.533 324L127.667 400.8"
        style={{ stroke: 'var(--acc)' }}
        strokeWidth="21.3333"
        strokeLinecap="round"
      />
      <path
        d="M383.667 153.333C407.231 153.333 426.333 134.231 426.333 110.667C426.333 87.1025 407.231 68 383.667 68C360.103 68 341 87.1025 341 110.667C341 134.231 360.103 153.333 383.667 153.333Z"
        style={{ fill: 'var(--sur)', stroke: 'var(--acc)' }}
        strokeWidth="21.3333"
      />
      <path
        d="M127.667 443.467C151.231 443.467 170.333 424.364 170.333 400.8C170.333 377.236 151.231 358.133 127.667 358.133C104.103 358.133 85 377.236 85 400.8C85 424.364 104.103 443.467 127.667 443.467Z"
        style={{ fill: 'var(--sur)', stroke: 'var(--acc)' }}
        strokeWidth="21.3333"
      />
      <path
        d="M161.8 247.2C194.79 247.2 221.533 220.456 221.533 187.467C221.533 154.477 194.79 127.733 161.8 127.733C128.81 127.733 102.067 154.477 102.067 187.467C102.067 220.456 128.81 247.2 161.8 247.2Z"
        style={{ fill: NODE_FILL }}
      />
      <path
        d="M349.533 383.733C382.523 383.733 409.267 356.99 409.267 324C409.267 291.01 382.523 264.267 349.533 264.267C316.544 264.267 289.8 291.01 289.8 324C289.8 356.99 316.544 383.733 349.533 383.733Z"
        style={{ fill: NODE_FILL }}
      />
    </svg>
  )
}
