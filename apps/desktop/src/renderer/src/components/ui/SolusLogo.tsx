// The Solus brand logo (SOLUSDEV-233): the bundled mark from
// assets/solus-logo.svg. Used in brand positions — the shell rail's home
// button, the auth wordmark, Settings. The SOL page header and the floating
// mini-orb deliberately keep the SolOrb: the orb is SOL's presence, the logo
// is the product's.
import logoUrl from '../../assets/solus-logo.svg'

interface SolusLogoProps {
  size?: number
}

export function SolusLogo({ size = 24 }: SolusLogoProps): React.JSX.Element {
  return (
    <img
      src={logoUrl}
      alt="Solus"
      draggable={false}
      style={{
        width: size,
        height: size,
        display: 'block',
        // The mark ships on its own dark tile; rounding reads as an app icon.
        borderRadius: Math.max(3, Math.round(size * 0.22)),
        flexShrink: 0
      }}
    />
  )
}
