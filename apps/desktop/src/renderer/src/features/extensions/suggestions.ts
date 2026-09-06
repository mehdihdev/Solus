// SOLUSDEV-246 / STORE ST3 — suggest a widget IN CONTEXT when its prerequisite
// connects: an EDA tool → BOM, a robot (runtime) → whatever requires it. Pure:
// the catalog, this project's installs and the connected kinds before/after a
// change in, the newly-available views out. Suggestions come from what is
// connected — never from what sells (wireflow store.md) — so the only rule is
// "a requirement group that was unmet is now met, and it is not installed here".
import type {
  ExtensionCatalogItemApi,
  ExtensionInstallApi
} from '../../lib/api/resources.extensions'
import type { ExtensionView, SourceKind } from './extension.types'
import { buildViews, connectedKinds, missingRequirements } from './extensionLogic'

export interface Suggestion {
  readonly view: ExtensionView
  /** The kinds that became connected and unlocked it (for the copy and the event). */
  readonly unlockedBy: readonly SourceKind[]
}

/** The connected kinds that appear in `after` but not in `before`. */
export function newlyConnectedKinds(
  before: readonly string[],
  after: readonly string[]
): SourceKind[] {
  const was = connectedKinds(before)
  return [...connectedKinds(after)].filter((kind) => !was.has(kind)).sort()
}

export function suggestionsAfterConnect(inputs: {
  catalog: readonly ExtensionCatalogItemApi[]
  installs: readonly ExtensionInstallApi[]
  beforeTypes: readonly string[]
  afterTypes: readonly string[]
  blocked?: ReadonlySet<string>
}): Suggestion[] {
  const unlocked = newlyConnectedKinds(inputs.beforeTypes, inputs.afterTypes)
  if (unlocked.length === 0) return []
  const before = connectedKinds(inputs.beforeTypes)
  const views = buildViews({
    catalog: [...inputs.catalog],
    installs: [...inputs.installs],
    details: {},
    connected: connectedKinds(inputs.afterTypes),
    blocked: inputs.blocked ?? new Set()
  })
  return views
    .filter(
      (view) =>
        view.availability === 'available' &&
        view.catalog.requires.length > 0 &&
        missingRequirements(view.catalog.requires, before).length > 0
    )
    .map((view) => ({
      view,
      unlockedBy: unlocked.filter((kind) => view.catalog.requires.some((g) => g.includes(kind)))
    }))
}

const KIND_NOUN: Readonly<Record<SourceKind, string>> = {
  code: 'a code host',
  eda: 'an EDA tool',
  cad: 'a CAD tool',
  canbus: 'a CAN bus',
  runtime: 'a robot'
}

/** The toast copy for one or more suggestions. */
export function suggestionToast(suggestions: readonly Suggestion[]): {
  title: string
  body: string
  slug: string
} | null {
  const first = suggestions[0]
  if (!first) return null
  const noun = first.unlockedBy[0] ? KIND_NOUN[first.unlockedBy[0]] : 'a source'
  const others = suggestions.length - 1
  const tail =
    others > 0 ? ` ${others} more ${others === 1 ? 'widget is' : 'widgets are'} available too.` : ''
  return {
    title: `${first.view.catalog.name} is now available`,
    body: `You connected ${noun}. ${first.view.catalog.summary}${tail}`,
    slug: first.view.catalog.slug
  }
}
