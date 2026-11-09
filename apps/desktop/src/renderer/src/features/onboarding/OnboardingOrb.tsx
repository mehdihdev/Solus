// SOL's orb for onboarding (SOLUSDEV-323): one element that persists across
// steps and changes state by attribute, so size and breathing ease between
// steps instead of remounting. Decorative — the words carry the meaning.
export type OrbState = 'big' | 'idle' | 'listening' | 'small' | 'working'

interface OnboardingOrbProps {
  state: OrbState
  /** `hub`: the small centre of the Connect ring. `compact`: the signed-out window. */
  size?: 'default' | 'hub' | 'compact'
}

export function OnboardingOrb({ state, size = 'default' }: OnboardingOrbProps): React.JSX.Element {
  return (
    <div className="ob-orb" data-state={state} data-size={size} aria-hidden="true">
      <div className="ob-orb-halo" />
      <div className="ob-orb-ring" />
      <div className="ob-orb-core" />
    </div>
  )
}
