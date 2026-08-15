// The post-auth SELECTION step: after OAuth, ask the backend what this source
// can be pointed at and let the user choose. Replaces the GitHub-only repo
// picker (SOLUSDEV-103) with one step that serves every connector.
//
// Nothing here knows what an item IS. The connector declares `selection`
// (single/multi, the config key, and the noun to show) in the live registry, and
// each item may carry the exact `config` choosing it writes. So GitHub picks one
// repository, Onshape picks many documents, and Fusion/SolidWorks/AutoCAD land
// with no change to this file.
import type { IntegrationSelection, SelectableItem } from '../../lib/api/resources'
import type { ConfigureContext, ConfigureOutcome, ConfigureStep } from './oauthConnect'
import type { ConnectionState } from './onboardingStore'

export interface SelectionConfigureDeps {
  selection: IntegrationSelection
  listSelectable: (projectId: string, sourceId: string) => Promise<SelectableItem[]>
  /** Push live connection state into the store (surfaces the picker). */
  onProgress: (state: ConnectionState) => void
  /** Resolve the in-tile picker: the chosen items, or null to cancel. */
  onSelect: (items: SelectableItem[]) => Promise<SelectableItem[] | null>
}

export const NOTHING_SELECTED_ERROR = 'Nothing selected.'

/** Plural of a connector's own noun: "repository" → "repositories".
 *  ponytail: -y/-s only. Every connector noun so far (repository, document,
 *  assembly, project, drawing) is regular; a connector needing "box"/"boxes"
 *  should declare its plural in `selection` instead of growing this. */
export function plural(label: string): string {
  return label.endsWith('y') ? `${label.slice(0, -1)}ies` : `${label}s`
}

export function nothingFoundError(label: string): string {
  return `No ${plural(label)} found for this account.`
}

/** The config a set of chosen items writes onto the source. */
export function selectionConfig(
  selection: IntegrationSelection,
  chosen: SelectableItem[]
): Record<string, unknown> {
  if (selection.mode === 'single') {
    // Single-select items carry their own config (GitHub needs repo AND branch),
    // falling back to the plain id for connectors that need nothing more.
    return chosen[0].config ?? { [selection.config_key]: chosen[0].id }
  }
  return { [selection.config_key]: chosen.map((item) => item.id) }
}

/** Progress copy for the indexing step: the item itself, or how many. */
function chosenLabel(selection: IntegrationSelection, chosen: SelectableItem[]): string {
  if (selection.mode === 'single') return chosen[0].name
  return `${chosen.length} ${chosen.length === 1 ? selection.label : plural(selection.label)}`
}

/** Build the post-auth configure step for a connector that declares a selection. */
export function selectionConfigureStep(deps: SelectionConfigureDeps): ConfigureStep {
  const { selection } = deps

  return async ({ projectId, sourceId }: ConfigureContext): Promise<ConfigureOutcome> => {
    deps.onProgress({
      phase: 'busy',
      label: `Discovering ${plural(selection.label)}…`,
      sourceId
    })
    const items = await deps.listSelectable(projectId, sourceId)
    if (items.length === 0) return { error: nothingFoundError(selection.label) }

    // A single-select connector with exactly one option needs no picker.
    const autoSelected = selection.mode === 'single' && items.length === 1
    const chosen = autoSelected ? [items[0]] : await pick(deps, sourceId, items)
    if (chosen === null) return { error: NOTHING_SELECTED_ERROR }
    // Selecting NOTHING is valid for a multi-select connector: the source is
    // connected and idle. Only single-select genuinely needs one.
    if (chosen.length === 0 && selection.mode === 'single') {
      return { error: NOTHING_SELECTED_ERROR }
    }

    return {
      config: selectionConfig(selection, chosen),
      label: chosen.length > 0 ? chosenLabel(selection, chosen) : `no ${plural(selection.label)}`
    }
  }
}

/** Surface the picker through the store, then await the user's choice. */
function pick(
  deps: SelectionConfigureDeps,
  sourceId: string,
  items: SelectableItem[]
): Promise<SelectableItem[] | null> {
  deps.onProgress({
    phase: 'busy',
    label: `Choose ${plural(deps.selection.label)} to track…`,
    sourceId,
    selectable: items,
    selectionMode: deps.selection.mode
  })
  return deps.onSelect(items)
}
