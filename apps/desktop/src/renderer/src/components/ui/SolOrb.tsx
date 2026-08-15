// The SOL "ball of energy" presence, ported from the orb gradient in
// TestDesign/app/auth.jsx (SolusWordmark) and shell SolOrb.
interface SolOrbProps {
  size?: number
  pulse?: boolean
  className?: string
}

export function SolOrb({ size = 18, pulse = false, className }: SolOrbProps): React.JSX.Element {
  // Pulse is a CSS class, not an inline animation, so the reduced-motion guard
  // in assets/main.css can switch it off (SOLX-02 perf/a11y budget).
  const classes = [className, pulse ? 'sol-orb-pulse' : null].filter(Boolean).join(' ')
  return (
    <span
      className={classes || undefined}
      aria-hidden
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        display: 'inline-block',
        flexShrink: 0,
        background: 'radial-gradient(circle at 35% 32%, var(--acc), transparent 72%)',
        boxShadow: '0 0 14px color-mix(in srgb, var(--acc) 40%, transparent)'
      }}
    />
  )
}
