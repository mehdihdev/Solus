// SOLUSDEV-246 / STORE ST3 — watch the open project's connected sources and,
// when a new KIND appears (an EDA tool, a robot…), raise one toast for the
// widget it unlocked, with "View" landing on that extension's Store detail.
// Reads the catalog and the install rows once per unlock — never on a timer —
// and records the suggestion as a data event (ADR-011). Best effort: any
// failure to read is silence, never an invented suggestion.
import { useEffect, useRef } from 'react'
import { devBypassActive } from '../../lib/supabase'
import {
  listExtensions,
  listProjectExtensions,
  postDataEvents
} from '../../lib/api/resources.extensions'
import type { Source } from '../../lib/api/resources'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useShellStore } from '../workspace/shellStore'
import { newlyConnectedKinds, suggestionToast, suggestionsAfterConnect } from './suggestions'

export interface SuggestionDeps {
  readonly loadCatalog?: typeof listExtensions
  readonly loadInstalls?: typeof listProjectExtensions
}

async function suggest(
  projectId: string,
  beforeTypes: readonly string[],
  afterTypes: readonly string[],
  deps: SuggestionDeps
): Promise<void> {
  const [catalog, installs] = await Promise.all([
    (deps.loadCatalog ?? listExtensions)({ limit: 100 }),
    (deps.loadInstalls ?? listProjectExtensions)(projectId)
  ])
  const found = suggestionsAfterConnect({
    catalog: catalog.data,
    installs: installs.data,
    beforeTypes,
    afterTypes
  })
  const toast = suggestionToast(found)
  if (!toast) return
  // A later project switch must not surface a suggestion for the old one.
  if (useWorkspaceStore.getState().project?.id !== projectId) return
  useShellStore.getState().setToast({
    kind: 'ok',
    title: toast.title,
    body: toast.body,
    action: 'View',
    screen: 'store',
    extensionSlug: toast.slug
  })
  if (devBypassActive || useAuthStore.getState().status !== 'authenticated') return
  void postDataEvents([
    {
      event_type: 'store.suggested',
      project_id: projectId,
      payload: {
        slug: toast.slug,
        unlocked_by: found[0]?.unlockedBy ?? [],
        candidates: found.length
      }
    }
  ]).catch(() => undefined)
}

/** Mount beside a live `useProjectSources()`; `status` must be `ready` for the
 *  list to count as known. The first known list is the baseline, never a trigger. */
export function useSourceSuggestions(
  projectId: string,
  sources: readonly Source[],
  status: 'loading' | 'ready' | 'offline',
  deps: SuggestionDeps = {}
): void {
  const known = useRef<{ projectId: string; types: readonly string[] } | null>(null)
  // Callers pass a fresh `deps` object per render; a ref keeps the effect keyed
  // on the source list alone (code review LOW).
  const depsRef = useRef(deps)
  depsRef.current = deps
  const types = sources.map((s) => s.type)
  const key = types.slice().sort().join('|')

  useEffect(() => {
    if (status !== 'ready') return
    const previous = known.current
    known.current = { projectId, types }
    if (!previous || previous.projectId !== projectId) return
    if (newlyConnectedKinds(previous.types, types).length === 0) return
    void suggest(projectId, previous.types, types, depsRef.current).catch(() => undefined)
    // `key` stands in for `types` so a re-render with the same list is inert.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, status, key])
}
