// SOLUSDEV-235 / EXT-12 — test doubles for BridgeDeps. Every seam is a vi.fn
// with a benign default so a test overrides only what it is about.
import { vi } from 'vitest'
import type { Source } from '../../../../lib/api/resources'
import type { BridgeDeps, TelemetrySample } from '../bridgeDeps'

export const FAKE_SOURCE: Source = {
  id: 's1',
  project_id: 'p1',
  type: 'github',
  name: 'firmware',
  status: 'connected',
  config: { repo: 'acme/fw', webhook_url: 'https://x/hook?token=SECRET' },
  account_login: 'maya',
  last_synced_at: '2026-09-01T00:00:00Z',
  last_error: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-09-01T00:00:00Z'
}

export interface FakeTelemetry {
  /** The most recent `onSamples` callback handed to `subscribe`. */
  push(samples: readonly TelemetrySample[]): void
  unsubscribe: ReturnType<typeof vi.fn>
}

export interface FakeBridgeDeps extends BridgeDeps {
  readonly fakeTelemetry: FakeTelemetry
}

export function fakeBridgeDeps(overrides: Partial<BridgeDeps> = {}): FakeBridgeDeps {
  let onSamples: ((s: readonly TelemetrySample[]) => void) | null = null
  const unsubscribe = vi.fn()
  const deps: BridgeDeps = {
    graph: {
      focusedEntity: vi.fn(() => null),
      getEntity: vi.fn(async (_p: string, entityId: string) => ({
        id: entityId,
        type: 'ic',
        domain: 'electrical',
        name: 'U1',
        source_key: 'U1'
      })),
      getNeighborhood: vi.fn(async () => ({ entities: [], edges: [], truncated: false })),
      search: vi.fn(async () => [])
    },
    focus: { get: vi.fn(() => null), propose: vi.fn(async () => true) },
    storage: {
      get: vi.fn(async () => 'stored'),
      set: vi.fn(async () => undefined),
      delete: vi.fn(async () => undefined)
    },
    net: {
      fetch: vi.fn(async () => ({
        ok: true as const,
        status: 200,
        headers: { 'content-type': 'application/json' },
        bodyBase64: btoa('{"a":1}')
      }))
    },
    sources: { list: vi.fn(async () => [FAKE_SOURCE]) },
    telemetry: {
      subscribe: vi.fn(
        async (
          _p: string,
          _ids: readonly string[],
          cb: (s: readonly TelemetrySample[]) => void
        ) => {
          onSamples = cb
          return unsubscribe
        }
      )
    },
    findings: { create: vi.fn(async () => ({ findingId: 'f1' })) },
    sol: { ask: vi.fn(async () => 'the answer') },
    ui: { openExternal: vi.fn(async () => undefined) },
    theme: vi.fn(() => ({ '--bg': '#0b0b0c', '--acc': '#ffb000' })),
    emitRefusal: vi.fn(),
    ...overrides
  }
  return {
    ...deps,
    fakeTelemetry: {
      push: (samples) => onSamples?.(samples),
      unsubscribe
    }
  }
}
