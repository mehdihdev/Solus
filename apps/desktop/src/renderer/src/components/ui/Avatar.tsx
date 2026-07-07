// Initials avatar, ported from Avatar in TestDesign/app/util.jsx. Hue is
// keyed off the first initial so a given teammate keeps a stable color.
const AV_HUES: Record<string, number> = { P: 210, M: 28, J: 150, A: 285, S: 0, R: 180, K: 60 }

interface AvatarProps {
  name: string
  size?: number
}

export function Avatar({ name, size = 26 }: AvatarProps): React.JSX.Element {
  const init = name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
  const hue = AV_HUES[init[0]] ?? (init.charCodeAt(0) * 47) % 360
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: 99,
        flexShrink: 0,
        background: `oklch(0.35 0.06 ${hue})`,
        border: '1px solid var(--bd)',
        color: `oklch(0.85 0.06 ${hue})`,
        fontSize: size * 0.38,
        fontWeight: 600,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: 'var(--font-ui)'
      }}
    >
      {init}
    </span>
  )
}
