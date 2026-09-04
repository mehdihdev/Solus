// SOLUSDEV-235 / EXT-12 — the unscoped methods plus `sources.list` and
// `findings.create` (§6.3).
import { BridgeFault } from '../bridgeErrors'
import { isGrantedOrigin, isStoreLink } from '../originAllow'
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

  /** SEC-C1: only a granted origin or an exact `store.links` URL may open,
   *  and at most 3 per 60 s per extension — the browser is otherwise a
   *  one-line exfiltration channel. `url` is schema-validated https; main's
   *  externalUrl guard re-checks the scheme. */
  'ui.openExternal': async (p, ctx) => {
    if (!isGrantedOrigin(ctx.policy, p.url) && !isStoreLink(ctx.policy, p.url)) {
      throw new BridgeFault('network_denied')
    }
    if (ctx.openExternalLimiter.tryAcquire() === 'rate_limited') {
      throw new BridgeFault('rate_limited')
    }
    ctx.openExternalLimiter.release()
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
