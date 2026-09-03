// SOLUSDEV-235 — pure rules over the extension catalog. Manifest + project
// state in, view out; no store, no fetch, so every Store surface renders the
// same answer and the rules are unit-testable in isolation.
import type {
  ExtensionAvailability,
  ExtensionInstallState,
  ExtensionManifest,
  ExtensionView,
  PermissionScope,
  Publisher,
  Requirements,
  RunFrequency,
  SourceKind
} from './extension.types'

/** Connected-source `type` (as the API reports it) → the kind extensions require. */
const SOURCE_TYPE_KIND: Readonly<Record<string, SourceKind>> = {
  github: 'code',
  gitlab: 'code',
  kicad: 'eda',
  altium: 'eda',
  onshape: 'cad',
  ros: 'runtime',
  canbus: 'canbus'
}

export const SOURCE_KIND_LABEL: Readonly<Record<SourceKind, string>> = {
  code: 'CODE',
  eda: 'EDA',
  cad: 'CAD',
  canbus: 'CANBUS',
  runtime: 'RUNTIME'
}

/** Long-form requirement names for the detail page's REQUIRES card. */
export const SOURCE_KIND_DESCRIPTION: Readonly<Record<SourceKind, string>> = {
  code: 'A code source (GitHub, GitLab)',
  eda: 'An EDA source (KiCad, Altium)',
  cad: 'A CAD source (Onshape)',
  canbus: 'A CAN bus connection',
  runtime: 'A runtime source (ROS, serial)'
}

export const PUBLISHER_LABEL: Readonly<Record<Publisher, string>> = {
  solus: 'SOLUS',
  community: 'COMMUNITY'
}

export const PERMISSION_TEXT: Readonly<Record<PermissionScope, { title: string; detail: string }>> =
  {
    'graph.read': { title: 'Read the context graph', detail: 'Entity names, relations, units' },
    'telemetry.read': {
      title: 'Read telemetry streams',
      detail: 'Live and recorded signal values'
    },
    'sources.read': {
      title: 'Read connected sources',
      detail: 'Source names, sync status, file lists'
    },
    'findings.write': {
      title: 'Raise findings',
      detail: 'Add cross-domain findings to this project'
    }
  }

export const RUN_FREQUENCY_OPTIONS: ReadonlyArray<{ value: RunFrequency; label: string }> = [
  { value: 'every_sync', label: 'On every sync' },
  { value: 'hourly', label: 'Hourly' },
  { value: 'daily', label: 'Daily' },
  { value: 'manual', label: 'Manual only' }
]

export const DEFAULT_INSTALL_STATE: ExtensionInstallState = {
  installed: false,
  enabled: true,
  runFrequency: 'every_sync'
}

/** The distinct source kinds a project's connected sources provide. Unknown types are ignored. */
export function connectedKinds(sourceTypes: readonly string[]): ReadonlySet<SourceKind> {
  const kinds = new Set<SourceKind>()
  for (const type of sourceTypes) {
    const kind = SOURCE_TYPE_KIND[type]
    if (kind) kinds.add(kind)
  }
  return kinds
}

/** The requirement groups none of `connected` satisfies. Empty means all met. */
export function missingRequirements(
  requires: Requirements,
  connected: ReadonlySet<SourceKind>
): Requirements {
  return requires.filter((group) => !group.some((kind) => connected.has(kind)))
}

/** "NEEDS CAD|EDA" style label for a set of unmet groups; ORs join with `|`, ANDs with `+`. */
export function requirementLabel(groups: Requirements): string {
  return groups.map((group) => group.map((k) => SOURCE_KIND_LABEL[k]).join('|')).join(' + ')
}

export function availabilityOf(
  state: ExtensionInstallState,
  missing: Requirements
): ExtensionAvailability {
  if (state.installed) return 'installed'
  return missing.length > 0 ? 'needs_source' : 'available'
}

/** The state an extension has before the user touches it: bundled ones start installed. */
export function initialInstallState(manifest: ExtensionManifest): ExtensionInstallState {
  return { ...DEFAULT_INSTALL_STATE, installed: manifest.defaultInstalled }
}

export function buildView(
  manifest: ExtensionManifest,
  state: ExtensionInstallState,
  connected: ReadonlySet<SourceKind>
): ExtensionView {
  const missing = missingRequirements(manifest.requires, connected)
  return { manifest, state, availability: availabilityOf(state, missing), missing }
}

/** Installed first (catalog order), then everything else — the Store's two sections. */
export function partitionViews(views: readonly ExtensionView[]): {
  installed: ExtensionView[]
  popular: ExtensionView[]
} {
  return {
    installed: views.filter((v) => v.state.installed),
    popular: views.filter((v) => !v.state.installed)
  }
}

/** Header meta line: "Solus · v1.0.0 · — installs · updated 2w ago". */
export function installsLabel(installs: number | null): string {
  return installs === null ? '— installs' : `${installs.toLocaleString()} installs`
}

const ID_RE = /^[a-z][a-z0-9-]*$/

/** Build-time sanity for the in-repo catalog: unique slug ids, non-empty copy. */
export function validateCatalog(catalog: readonly ExtensionManifest[]): string[] {
  const problems: string[] = []
  const seen = new Set<string>()
  for (const m of catalog) {
    if (!ID_RE.test(m.id)) problems.push(`${m.id}: id must be a lowercase slug`)
    if (seen.has(m.id)) problems.push(`${m.id}: duplicate id`)
    seen.add(m.id)
    if (!m.name.trim()) problems.push(`${m.id}: name is empty`)
    if (!m.summary.trim()) problems.push(`${m.id}: summary is empty`)
    if (m.requires.some((group) => group.length === 0))
      problems.push(`${m.id}: empty requirement group`)
  }
  return problems
}
