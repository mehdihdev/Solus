// SOLUSDEV-235 / EXT-12 — `graph.*` (§6.3): every read is bound to the HOST's
// project; the frame never names one.
import type { HandlerTable } from './context'

type GraphMethod = 'graph.getFocus' | 'graph.getEntity' | 'graph.getNeighborhood' | 'graph.search'

export const graphHandlers: HandlerTable<GraphMethod> = {
  'graph.getFocus': async (_p, ctx) => ctx.deps.graph.focusedEntity(),

  'graph.getEntity': (p, ctx) => ctx.deps.graph.getEntity(ctx.policy.projectId, p.entityId),

  'graph.getNeighborhood': async (p, ctx) => {
    const n = await ctx.deps.graph.getNeighborhood(
      ctx.policy.projectId,
      p.entityId,
      p.depth,
      p.limit
    )
    return { entities: n.entities, relations: n.edges }
  },

  'graph.search': (p, ctx) => ctx.deps.graph.search(ctx.policy.projectId, p.q, p.types, p.limit)
}
