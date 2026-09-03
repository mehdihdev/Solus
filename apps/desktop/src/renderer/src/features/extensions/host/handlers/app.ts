// SOLUSDEV-235 / EXT-12 — the unscoped methods plus `sources.list` and
// `findings.create` (§6.3).
import { BridgeFault } from '../bridgeErrors'
import type { HandlerTable } from './context'

type AppMethod =
  | 'ui.ready'
  | 'settings.get'
  | 'ui.openExternal'
  | 'sources.list'
  | 'findings.create'

export const appHandlers: HandlerTable<AppMethod> = {
  'ui.ready': async (_p, ctx) => {
    ctx.session.markReady()
    return {}
  },

  /** Own declared values only — a fresh copy, never the host's object. */
  'settings.get': async (_p, ctx) => ({ ...ctx.settings }),

  /** `url` is schema-validated https; main's externalUrl guard re-checks. */
  'ui.openExternal': async (p, ctx) => {
    await ctx.deps.ui.openExternal(p.url)
    return {}
  },

  /** Projected to the §6.3 shape: no config, no credentials, no URLs. */
  'sources.list': async (_p, ctx) => {
    const sources = await ctx.deps.sources.list(ctx.policy.projectId)
    return sources.map((s) => ({
      id: s.id,
      kind: s.type,
      name: s.name,
      status: s.status,
      lastSyncAt: s.last_synced_at
    }))
  },

  'findings.create': async (p, ctx) => {
    if (!ctx.deps.findings) throw new BridgeFault('unavailable')
    return ctx.deps.findings.create(ctx.policy.projectId, p)
  }
}
