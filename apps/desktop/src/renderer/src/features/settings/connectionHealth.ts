// One status word per account grant for Settings › Connected tools
// (SOLUSDEV-318) — the same precedence Home badges (SOLUSDEV-244 / H4).
import type { Connection } from '../../lib/api/resources'

export type HealthTone = 'ok' | 'warn' | 'err' | 'mut'

export interface ConnectionHealthView {
  label: string
  tone: HealthTone
}

export function connectionHealth(c: Connection): ConnectionHealthView {
  if (c.status === 'pending') return { label: 'Pending', tone: 'mut' }
  if (c.needs_reauth === 'token_error' || c.health === 'token_expired') {
    return { label: 'Reconnect', tone: 'warn' }
  }
  if (c.status === 'error') return { label: 'Error', tone: 'err' }
  if (c.health === 'degraded') return { label: 'Degraded', tone: 'warn' }
  return { label: 'Connected', tone: 'ok' }
}
