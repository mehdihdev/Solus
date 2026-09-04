// SOLUSDEV-235 / EXT-12 — the production BridgeDeps: every seam wired to the
// typed API client (user session), the focus/workspace/settings stores, and
// the desktop preload bridge. bridgeHost.ts never imports any of these
// directly, so the pipeline stays provable with fakes.
import { api } from '../../../lib/api/client'
import { getGraphNeighborhood, listSources, type Entity } from '../../../lib/api/resources'
import {
  deleteExtensionStorage,
  getExtensionStorage,
  putExtensionStorage
} from '../../../lib/api/resources.extensions'
import { getDesktopExtensionsBridge } from '../../../lib/desktopBridge'
import { useSettingsStore } from '../../../store/settingsStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { buildThemeVars } from '../../../theme/applyTheme'
import { selectFocusedEntity, useFocusStore } from '../../workspace/focusStore'
import { toSharedFocus } from '../../workspace/useSharedFocus'
import type { BridgeDeps, BridgeGraphDeps } from './bridgeDeps'
import { createAttributedSolAsk } from './handlers/sol'
import { createRefusalReporter } from './refusalReporter'

const seg = encodeURIComponent

/** GET /projects/{id}/entities?q=&type=&limit= (API.md §2.4). The route takes
 *  ONE `type`; several are narrowed client-side. */
async function searchEntities(
  projectId: string,
  q: string,
  types: readonly string[],
  limit: number
): Promise<Entity[]> {
  const params = new URLSearchParams({ q, limit: String(limit) })
  if (types.length === 1) params.set('type', types[0])
  const entities = await api.request<Entity[]>(`/projects/${seg(projectId)}/entities?${params}`)
  return types.length > 1 ? entities.filter((e) => types.includes(e.type)) : entities
}

const graph: BridgeGraphDeps = {
  focusedEntity: () => selectFocusedEntity(useFocusStore.getState()),
  getEntity: (projectId, entityId) =>
    api.request<unknown>(`/projects/${seg(projectId)}/entities/${seg(entityId)}`),
  getNeighborhood: (projectId, entityId, depth, limit) =>
    getGraphNeighborhood(projectId, entityId, { depth, limit }),
  search: searchEntities
}

/** Current theme as the CSS-var map `applyTheme` writes to :root. */
export function currentThemeVars(): Record<string, string> {
  const { theme, accent } = useSettingsStore.getState()
  return buildThemeVars(theme, accent)
}

/** One renderer-wide reporter: the per-extension budget spans every frame. */
const refusals = createRefusalReporter({
  projectId: () => useWorkspaceStore.getState().project?.id
})

export function defaultBridgeDeps(): BridgeDeps {
  const extensions = getDesktopExtensionsBridge()
  return {
    graph,
    focus: {
      get: () =>
        toSharedFocus(
          selectFocusedEntity(useFocusStore.getState()),
          useWorkspaceStore.getState().project?.id
        ),
      // The focus engine is project-bound; a proposal for another project is
      // refused here as well as by the handler's descend() check.
      propose: async (next) => {
        if (useWorkspaceStore.getState().project?.id !== next.entity.projectId) return false
        await useFocusStore.getState().focus(next.entity.entityId)
        return true
      }
    },
    storage: {
      get: async (projectId, slug, key) => (await getExtensionStorage(projectId, slug, key)).value,
      set: async (projectId, slug, key, value) => {
        await putExtensionStorage(projectId, slug, key, value)
      },
      delete: (projectId, slug, key) => deleteExtensionStorage(projectId, slug, key)
    },
    net: extensions ? { fetch: (request) => extensions.netFetch(request) } : null,
    sources: { list: (projectId) => listSources(projectId) },
    // Not wired in EXT-12: the Live Bench stream fan-out and a findings write
    // route do not exist yet; the handlers answer `unavailable`.
    telemetry: null,
    findings: null,
    sol: createAttributedSolAsk(),
    ui: {
      // window.open in the renderer goes through main's setWindowOpenHandler →
      // externalUrl.ts (https only → shell.openExternal, else denied).
      openExternal: async (url) => {
        window.open(url, '_blank', 'noopener,noreferrer')
      }
    },
    theme: currentThemeVars,
    // Data-collection hook (§6.4 `extension.bridge_refused`), batched and
    // budgeted (SEC-H4/M1) through POST /events (API.md §2.13).
    emitRefusal: (refusal) => refusals.emit(refusal)
  }
}
