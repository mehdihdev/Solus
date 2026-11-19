// SOLUSDEV-329 — window.solus.mcpRuntime: a narrow typed surface over the
// §9 channels; pushes are shape-checked before they reach the renderer.
import { describe, expect, it, vi } from 'vitest'
import { MCP_RUNTIME_CHANNELS } from './channels'
import { createMcpRuntimeBridge, type McpRuntimeIpcRenderer } from './preloadBridge'

function fakeIpc(): McpRuntimeIpcRenderer & {
  listeners: Map<string, (event: unknown, raw: unknown) => void>
} {
  const listeners = new Map<string, (event: unknown, raw: unknown) => void>()
  return {
    listeners,
    invoke: vi.fn(async () => ({ ok: true })),
    on: (channel, listener) => void listeners.set(channel, listener),
    removeListener: (channel) => void listeners.delete(channel)
  }
}

describe('createMcpRuntimeBridge', () => {
  it('invokes each §9 channel with its request', async () => {
    const ipc = fakeIpc()
    const bridge = createMcpRuntimeBridge(ipc)
    await bridge.detect()
    await bridge.status()
    await bridge.getChoice()
    await bridge.choose({ mode: 'path' })
    await bridge.provision({ trigger: 'repair', forks: ['local'] })
    await bridge.installManaged({ consent: true })
    await bridge.cancel({ runId: 'r1' })
    expect(vi.mocked(ipc.invoke).mock.calls).toEqual([
      [MCP_RUNTIME_CHANNELS.detect],
      [MCP_RUNTIME_CHANNELS.status],
      [MCP_RUNTIME_CHANNELS.getChoice],
      [MCP_RUNTIME_CHANNELS.choose, { mode: 'path' }],
      [MCP_RUNTIME_CHANNELS.provision, { trigger: 'repair', forks: ['local'] }],
      [MCP_RUNTIME_CHANNELS.installManaged, { consent: true }],
      [MCP_RUNTIME_CHANNELS.cancel, { runId: 'r1' }]
    ])
  })

  it('delivers well-formed progress pushes and drops the rest; unsubscribe removes the listener', () => {
    const ipc = fakeIpc()
    const handler = vi.fn()
    const off = createMcpRuntimeBridge(ipc).onProgress(handler)
    const listener = ipc.listeners.get(MCP_RUNTIME_CHANNELS.progress)!
    const push = {
      runId: 'r1',
      event: { type: 'done', outcome: 'ok', ok: 1, failed: 0, skipped: 0 }
    }
    listener({}, push)
    listener({}, { runId: 1, event: {} })
    listener({}, { runId: 'r1', event: null })
    listener({}, 'x')
    expect(handler).toHaveBeenCalledTimes(1)
    expect(handler).toHaveBeenCalledWith(push)
    off()
    expect(ipc.listeners.has(MCP_RUNTIME_CHANNELS.progress)).toBe(false)
  })
})
