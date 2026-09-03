// SOLUSDEV-235 / EXT-12 — `storage.*` over the route plan's §7 store. Values
// are opaque strings to the bridge (§6.3 `value: string | null`); a miss is a
// null, not an error; quota and size refusals come back from the server.
import { ApiError } from '../../../../lib/api/envelope.types'
import type { HandlerTable } from './context'

type StorageMethod = 'storage.get' | 'storage.set' | 'storage.delete'

const isMiss = (error: unknown): boolean => error instanceof ApiError && error.status === 404

/** The server stores any JSON; the bridge hands the frame text. */
function asText(value: unknown): string | null {
  if (value === null || value === undefined) return null
  return typeof value === 'string' ? value : JSON.stringify(value)
}

export const storageHandlers: HandlerTable<StorageMethod> = {
  'storage.get': async (p, ctx) => {
    try {
      const value = await ctx.deps.storage.get(ctx.policy.projectId, ctx.policy.extensionId, p.key)
      return { value: asText(value) }
    } catch (error) {
      if (isMiss(error)) return { value: null }
      throw error
    }
  },

  'storage.set': async (p, ctx) => {
    await ctx.deps.storage.set(ctx.policy.projectId, ctx.policy.extensionId, p.key, p.value)
    return {}
  },

  'storage.delete': async (p, ctx) => {
    try {
      await ctx.deps.storage.delete(ctx.policy.projectId, ctx.policy.extensionId, p.key)
    } catch (error) {
      if (!isMiss(error)) throw error
    }
    return {}
  }
}
