// SOLUSDEV-235 / EXT-12 — `telemetry.*` (§6.3, §6.5). The frame has no
// socket: the host fans out its own per-project stream, batched.
import { BridgeFault } from '../bridgeErrors'
import { BRIDGE_LIMITS } from '../bridgeProtocol'
import type { HandlerTable } from './context'

export const telemetryHandlers: HandlerTable<'telemetry.subscribe' | 'telemetry.unsubscribe'> = {
  'telemetry.subscribe': async (p, ctx) => {
    const { telemetry } = ctx.deps
    if (!telemetry) throw new BridgeFault('unavailable')
    const registry = ctx.session.telemetry
    if (registry.count() >= BRIDGE_LIMITS.subscriptions)
      throw new BridgeFault('invalid_params', 'Too many subscriptions')
    const subscriptionId = registry.nextId()
    // Reserve the slot BEFORE awaiting so two concurrent subscribes cannot both
    // pass the cap check.
    registry.add(subscriptionId, () => undefined)
    try {
      const unsubscribe = await telemetry.subscribe(ctx.policy.projectId, p.signalIds, (samples) =>
        registry.push(subscriptionId, samples)
      )
      // Unsubscribed while we were awaiting → release the real subscription now.
      if (registry.has(subscriptionId)) registry.add(subscriptionId, unsubscribe)
      else unsubscribe()
    } catch (error) {
      registry.remove(subscriptionId)
      throw error
    }
    return { subscriptionId }
  },

  'telemetry.unsubscribe': async (p, ctx) => {
    if (!ctx.session.telemetry.remove(p.subscriptionId)) throw new BridgeFault('invalid_params')
    return {}
  }
}
