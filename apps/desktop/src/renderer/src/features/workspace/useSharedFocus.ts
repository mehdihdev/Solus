// System A → System B focus adapter.
//
// The workspace has two widget contracts today: the local one (widget.contract.ts,
// hosted by WidgetHost) and the shared-types one (@solus/shared-types, implemented
// by the manifest widgets — LiveBenchWidget). They cannot render each other, and
// unifying them is its own ticket. This hook is the seam: it projects the
// workspace's focus store into the shared `Focus` shape, so a shared-types widget
// can mount anywhere in the app without either contract changing.
//
// Referential stability is load-bearing, not a nicety: LiveBenchWidget's polling
// effect is keyed on the focus OBJECT, so a fresh object per render would tear
// down and restart its interval on every store emission. The memo below returns
// the same object until the cached entity or the project actually changes — and
// deriving from the CACHED entity (whose key includes the project id) makes a
// project switch an automatic cache miss → null, never a stale cross-project poll.
import { useMemo } from 'react'
import { DOMAINS, type Domain, type Focus, type FocusStep } from '@solus/shared-types'
import type { Entity } from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { selectFocusedEntity, useFocusStore } from './focusStore'

function isDomain(value: string): value is Domain {
  return (DOMAINS as readonly string[]).includes(value)
}

/**
 * Pure mapping, exported for tests. Null means "nothing to show" — an unknown
 * domain is a contract drift between the backend enum and shared-types
 * (ADR-027 says they mirror), and answering null keeps the widget honest
 * instead of fabricating a focus.
 */
export function toSharedFocus(
  entity: Entity | null,
  projectId: string | null | undefined
): Focus | null {
  if (!entity || !projectId || !isDomain(entity.domain)) return null
  return {
    entity: { projectId, entityId: entity.id },
    domain: entity.domain,
    label: entity.name,
    // Empty path is the contract's documented "landed here directly" case —
    // a list selection has no breadcrumb trail.
    path: []
  }
}

/** The current shared-shape focus, or null when nothing (valid) is focused. */
export function useSharedFocus(): Focus | null {
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const entity = useFocusStore(selectFocusedEntity)
  const path = useFocusStore((s) => s.path)
  return useMemo(() => {
    const focus = toSharedFocus(entity, projectId)
    if (!focus || path.some((step: FocusStep) => step.entity.projectId !== projectId)) return null
    return { ...focus, path }
  }, [entity, projectId, path])
}
