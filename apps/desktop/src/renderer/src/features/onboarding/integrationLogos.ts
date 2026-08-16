// Bundled integration logos (SOLUSDEV-165). Drop an svg (preferred) or png
// named by the lowercase provider id into `assets/integrations/` —
// `github.svg`, `kicad.svg`, … — and it is picked up here with no code
// change. A provider without a logo falls back to its letter mark, so an
// unknown connector still renders.
const bundled = import.meta.glob('../../assets/integrations/*.{svg,png}', {
  eager: true,
  query: '?url',
  import: 'default'
}) as Record<string, string>

/** `../../assets/integrations/GitHub.svg` → `github`. */
function providerIdFrom(path: string): string | null {
  const base = path.split('/').pop() ?? ''
  const id = base.replace(/\.(svg|png)$/i, '').toLowerCase()
  return id ? id : null
}

/** Pure mapping from a glob result to `{ providerId: url }`, svg beating png. */
export function logoMapFrom(files: Record<string, string>): Record<string, string> {
  const map: Record<string, string> = {}
  const ranked = Object.entries(files).sort(([a], [b]) => a.localeCompare(b))
  for (const [path, url] of ranked) {
    const id = providerIdFrom(path)
    if (!id) continue
    const isSvg = /\.svg$/i.test(path)
    if (!(id in map) || isSvg) map[id] = url
  }
  return map
}

const LOGOS = logoMapFrom(bundled)

/** The bundled logo url for a provider id, or null for the letter-mark fallback. */
export function integrationLogo(id: string): string | null {
  return LOGOS[id.toLowerCase()] ?? null
}
