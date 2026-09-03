// SOLUSDEV-235 / EXT-12 — `focus.*` (§6.3). A proposal names an entity; the
// HOST supplies the project (never the frame), and `descend()` is the arbiter
// that refuses a cross-project trail (docs/contracts/focus.md).
import { descend, type Focus } from '@solus/shared-types'
import { BridgeFault } from '../bridgeErrors'
import type { ValidatedParams } from '../paramsSchema'
import type { HandlerTable } from './context'

type Proposal = ValidatedParams['focus.propose']

function target(p: Proposal, projectId: string): Focus {
  return {
    entity: { projectId, entityId: p.entityId },
    domain: p.domain,
    ...(p.label === undefined ? {} : { label: p.label }),
    path: []
  }
}

/** With a relation the hop is recorded via `descend`; without one the frame
 *  "landed here directly" (empty path). Either way a current focus from
 *  another project is a stale host and the proposal is `invalid_params`. */
export function arbitrateFocus(current: Focus | null, p: Proposal, projectId: string): Focus {
  const next = target(p, projectId)
  if (current === null) return next
  if (current.entity.projectId !== projectId) throw new BridgeFault('invalid_params')
  if (p.relation === undefined) return next
  try {
    return descend(current, { ...next, relation: p.relation })
  } catch {
    throw new BridgeFault('invalid_params')
  }
}

export const focusHandlers: HandlerTable<'focus.get' | 'focus.propose'> = {
  'focus.get': async (_p, ctx) => ctx.deps.focus.get(),

  'focus.propose': async (p, ctx) => {
    const next = arbitrateFocus(ctx.deps.focus.get(), p, ctx.policy.projectId)
    return { accepted: await ctx.deps.focus.propose(next) }
  }
}
