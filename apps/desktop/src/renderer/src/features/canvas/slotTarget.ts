// SOLUSDEV-235 / EXT-15 — what a layout ref resolved to (pure; no React).
import type { WidgetSizeHint } from '@solus/shared-types'
import { parseWidgetRef } from './layout'
import type { BuiltinWidgetEntry, ExtensionWidgetEntry } from './useAvailableWidgets'

/** An extension whose install snapshot has not loaded yet renders anyway
 *  (`entry: null`) — the frame reports its own state. */
export type SlotTarget =
  | { readonly kind: 'builtin'; readonly entry: BuiltinWidgetEntry }
  | { readonly kind: 'ext'; readonly slug: string; readonly entry: ExtensionWidgetEntry | null }

/** Null only for a ref the pruner has not yet removed (unknown built-in, malformed). */
export function resolveSlotTarget(
  ref: string,
  builtins: readonly BuiltinWidgetEntry[],
  extensions: readonly ExtensionWidgetEntry[]
): SlotTarget | null {
  const parsed = parseWidgetRef(ref)
  if (parsed === null) return null
  if (parsed.kind === 'builtin') {
    const entry = builtins.find((b) => b.id === parsed.id)
    return entry === undefined ? null : { kind: 'builtin', entry }
  }
  const entry = extensions.find((e) => e.slug === parsed.slug) ?? null
  return { kind: 'ext', slug: parsed.slug, entry }
}

export function slotTitle(target: SlotTarget): string {
  if (target.kind === 'builtin') return target.entry.title
  return target.entry?.name ?? target.slug
}

export function slotSizeHint(target: SlotTarget): WidgetSizeHint | undefined {
  return target.kind === 'builtin' ? target.entry.size : target.entry?.size
}
