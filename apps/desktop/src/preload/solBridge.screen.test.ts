// SOLUSDEV-324: window.solus.sol.takeScreen — the summon picture reaches the
// renderer only in the shape main produces; anything else is null (no pixels
// of an unexpected shape ever ride a turn).
import { describe, expect, it, vi } from 'vitest'
import { createSolBridge, type SolBridgeIpc } from './solBridge'
import { SOL_WINDOW_CHANNELS } from '../main/sol-window/solWindow.constants'
import type { SolScreenPayload } from '../main/capture/summonShot'

const SHOT: SolScreenPayload = {
  jpegBase64: '/9j/AAAA',
  width: 1920,
  height: 1080,
  source: { app: 'Firefox', title: 'Gradescope' },
  capturedAt: 1
}

function bridgeAnswering(raw: unknown): {
  invoke: ReturnType<typeof vi.fn>
  bridge: ReturnType<typeof createSolBridge>
} {
  const invoke = vi.fn(async () => raw)
  const ipc: SolBridgeIpc = { invoke, on: () => undefined, removeListener: () => undefined }
  return { invoke, bridge: createSolBridge(ipc) }
}

describe('takeScreen', () => {
  it('invokes sol:take-screen and passes a well-formed picture through', async () => {
    const { invoke, bridge } = bridgeAnswering(SHOT)
    await expect(bridge.takeScreen?.()).resolves.toEqual(SHOT)
    expect(invoke).toHaveBeenCalledWith(SOL_WINDOW_CHANNELS.takeScreen)
  })

  it('null (nothing captured, or not the pill) stays null', async () => {
    await expect(bridgeAnswering(null).bridge.takeScreen?.()).resolves.toBeNull()
  })

  it.each([
    ['missing data', { ...SHOT, jpegBase64: undefined }],
    ['non-numeric size', { ...SHOT, width: '1920' }],
    ['malformed source', { ...SHOT, source: { app: 1 } }],
    ['not an object', 'pixels']
  ])('drops a malformed answer (%s)', async (_label, raw) => {
    await expect(bridgeAnswering(raw).bridge.takeScreen?.()).resolves.toBeNull()
  })

  it('an IPC failure resolves null — a turn is never lost to the picture', async () => {
    const ipc: SolBridgeIpc = {
      invoke: async () => {
        throw new Error('no handler')
      },
      on: () => undefined,
      removeListener: () => undefined
    }
    await expect(createSolBridge(ipc).takeScreen?.()).resolves.toBeNull()
  })
})
