// Compact relative timestamps for feeds ("12 min ago", "3h ago", "3d ago").
const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

export function relativeTime(iso: string, now: number = Date.now()): string {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const delta = Math.max(0, now - t)
  if (delta < MINUTE) return 'now'
  if (delta < HOUR) return `${Math.floor(delta / MINUTE)} min ago`
  if (delta < DAY) return `${Math.floor(delta / HOUR)}h ago`
  if (delta < 30 * DAY) return `${Math.floor(delta / DAY)}d ago`
  const d = new Date(t)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
}
