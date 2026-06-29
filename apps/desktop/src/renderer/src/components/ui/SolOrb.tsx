// The SOL "ball of energy" presence, ported from the orb gradient in
// TestDesign/app/auth.jsx (SolusWordmark) and shell SolOrb.
interface SolOrbProps {
  size?: number
  pulse?: boolean
  className?: string
}

export function SolOrb({ size = 18, pulse = false, className }: SolOrbProps): React.JSX.Element {
  return (
    <span
      className={className}
      aria-hidden
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        display: 'inline-block',
        flexShrink: 0,
        background: 'radial-gradient(circle at 35% 32%, var(--acc), transparent 72%)',
        boxShadow: '0 0 14px color-mix(in srgb, var(--acc) 40%, transparent)',
        animation: pulse ? 'sol-orb-pulse 2.4s ease-in-out infinite' : undefined
      }}
    />
  )
}
