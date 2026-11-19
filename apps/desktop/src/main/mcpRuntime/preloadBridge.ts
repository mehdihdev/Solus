// SOLUSDEV-329 — the renderer end of mcpRuntime:* (docs/architecture/
// mcp-fork-runtime.md §9), exposed as window.solus.mcpRuntime. A pure factory
// over an injected ipcRenderer (bound in preload/index.ts) so the renderer
// never holds raw ipcRenderer. Progress pushes are re-validated against the
// §6 shapes before delivery: main already did, but this is the trust edge.
import { MCP_RUNTIME_CHANNELS, type McpRuntimeBridge, type ProgressPush } from './channels'
import { parseRuntimeLine } from './protocol'

/** Structural slice of ipcRenderer — just what the bridge needs. */
export interface McpRuntimeIpcRenderer {
  invoke(channel: string, ...args: unknown[]): Promise<unknown>
  on(channel: string, listener: (event: unknown, raw: unknown) => void): void
  removeListener(channel: string, listener: (event: unknown, raw: unknown) => void): void
}

const RUN_ID_MAX = 64

function parsePush(raw: unknown): ProgressPush | null {
  if (typeof raw !== 'object' || raw === null) return null
  const { runId, event } = raw as Record<string, unknown>
  if (typeof runId !== 'string' || runId.length > RUN_ID_MAX) return null
  if (typeof event !== 'object' || event === null || Array.isArray(event)) return null
  const parsed = parseRuntimeLine(JSON.stringify({ ...event, v: 1 }))
  return parsed === null ? null : { runId, event: parsed }
}

export function createMcpRuntimeBridge(ipc: McpRuntimeIpcRenderer): McpRuntimeBridge {
  const c = MCP_RUNTIME_CHANNELS
  const call = <T>(channel: string, ...args: unknown[]): Promise<T> =>
    ipc.invoke(channel, ...args) as Promise<T>
  return {
    detect: () => call(c.detect),
    status: () => call(c.status),
    getChoice: () => call(c.getChoice),
    choose: (request) => call(c.choose, request),
    provision: (request) => call(c.provision, request),
    installManaged: (request) => call(c.installManaged, request),
    cancel: (request) => call(c.cancel, request),
    onProgress(handler) {
      const listener = (_event: unknown, raw: unknown): void => {
        const push = parsePush(raw)
        if (push !== null) handler(push)
      }
      ipc.on(c.progress, listener)
      return () => ipc.removeListener(c.progress, listener)
    }
  }
}
