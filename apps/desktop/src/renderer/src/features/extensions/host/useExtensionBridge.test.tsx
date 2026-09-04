// SOLUSDEV-235 / EXT-12 — hook lifecycle under jsdom: listener registration,
// source filtering, load → init, ui.ready → ready, store → events, teardown.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, waitFor, fireEvent } from '@testing-library/react'
import { useRef } from 'react'
import { useFocusStore } from '../../workspace/focusStore'
import { useSettingsStore } from '../../../store/settingsStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import type { BridgeOutbound } from './bridgeProtocol'
import type { BridgePolicy } from './policySnapshot'
import { fakeBridgeDeps, type FakeBridgeDeps } from './testing/fakeBridgeDeps'
import { useExtensionBridge, type UseExtensionBridgeOptions } from './useExtensionBridge'

const policy: BridgePolicy = {
  extensionId: 'bom',
  version: '1.2.0',
  projectId: 'p1',
  grantedScopes: ['graph.read', 'focus.read'],
  grantedNetwork: [],
  enabled: true,
  blocked: false,
  mode: 'page'
}

type HarnessProps = Omit<UseExtensionBridgeOptions, 'frameRef'>

function Harness(props: HarnessProps): React.JSX.Element {
  const frameRef = useRef<HTMLIFrameElement | null>(null)
  const { ready, dropped } = useExtensionBridge({ ...props, frameRef })
  return (
    <>
      <iframe ref={frameRef} title="ext" />
      <span data-testid="ready">{String(ready)}</span>
      <span data-testid="dropped">{dropped}</span>
    </>
  )
}

interface Mounted {
  frameWindow: Window
  received: BridgeOutbound[]
  deps: FakeBridgeDeps
  send(data: unknown, source?: unknown): void
  unmount(): void
  rerender(props: HarnessProps): void
}

function mount(overrides: Partial<HarnessProps> = {}): Mounted {
  const deps = (overrides.deps as FakeBridgeDeps | undefined) ?? fakeBridgeDeps()
  const props: HarnessProps = { policy, settings: { refresh: 'hourly' }, deps, ...overrides }
  const view = render(<Harness {...props} />)
  const iframe = screen.getByTitle('ext') as HTMLIFrameElement
  const frameWindow = iframe.contentWindow as Window
  const received: BridgeOutbound[] = []
  frameWindow.addEventListener('message', (e) => received.push((e as MessageEvent).data))
  return {
    frameWindow,
    received,
    deps,
    send: (data, source = frameWindow) =>
      fireEvent(
        window,
        new MessageEvent('message', { data, source: source as Window, origin: 'null' })
      ),
    unmount: () => view.unmount(),
    rerender: (next) => view.rerender(<Harness {...next} />)
  }
}

const readyRequest = { v: 1, id: 'r1', method: 'ui.ready', params: {} }

beforeEach(() => {
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'P1' } })
  useFocusStore.getState().reset()
})

afterEach(() => {
  useFocusStore.getState().reset()
  useWorkspaceStore.setState({ project: null })
})

describe('useExtensionBridge', () => {
  it('posts init on the iframe load and flips ready on ui.ready', async () => {
    const onReady = vi.fn()
    const m = mount({ onReady })
    const iframe = screen.getByTitle('ext')
    fireEvent.load(iframe)
    await waitFor(() => expect(m.received.at(-1)).toMatchObject({ event: 'init' }))
    expect(m.received[0]).toMatchObject({
      event: 'init',
      data: {
        extensionId: 'bom',
        projectHandle: expect.any(String),
        mode: 'page',
        settings: { refresh: 'hourly' }
      }
    })
    expect(JSON.stringify(m.received[0])).not.toContain('p1')
    expect(screen.getByTestId('ready').textContent).toBe('false')
    m.send(readyRequest)
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'))
    expect(onReady).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(m.received.at(-1)).toEqual({ v: 1, id: 'r1', ok: true, result: {} }))
  })

  it('ignores messages from other sources and counts malformed ones from the frame', async () => {
    const m = mount()
    m.send(readyRequest, window)
    m.send(readyRequest, null)
    // SEC-L1: the frame's own window, but a non-opaque origin — dropped too.
    fireEvent(
      window,
      new MessageEvent('message', {
        data: readyRequest,
        source: m.frameWindow,
        origin: 'https://app.solus.dev'
      })
    )
    await act(async () => undefined)
    // jsdom fires the iframe's own about:blank `load`, so an `init` EVENT may be
    // present; what must be absent is any RESPONSE — a foreign source gets none.
    const responses = (): BridgeOutbound[] => m.received.filter((msg) => 'id' in msg)
    expect(responses()).toEqual([])
    expect(screen.getByTestId('ready').textContent).toBe('false')
    m.send({ v: 2, id: 'x' })
    await waitFor(() => expect(screen.getByTestId('dropped').textContent).toBe('1'))
    expect(responses()).toEqual([])
  })

  it('forwards focus changes as focus.changed once ready, deduplicated', async () => {
    const m = mount()
    m.send(readyRequest)
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'))
    const entity = { id: 'e1', type: 'ic', domain: 'electrical', name: 'U1', source_key: 'U1' }
    act(() => {
      useFocusStore.setState({
        focusedEntityId: 'e1',
        status: 'ready',
        cache: { 'p1:e1@1': { entities: [entity], edges: [], truncated: false } }
      })
    })
    await waitFor(() =>
      expect(m.received.at(-1)).toEqual({
        v: 1,
        event: 'focus.changed',
        data: {
          entity: { projectId: 'p1', entityId: 'e1' },
          domain: 'electrical',
          label: 'U1',
          path: []
        }
      })
    )
    const count = m.received.length
    act(() => useFocusStore.setState({ error: null }))
    await act(async () => undefined)
    expect(m.received.length).toBe(count)
  })

  it('forwards theme changes and settings prop changes', async () => {
    const m = mount()
    m.send(readyRequest)
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'))
    act(() => useSettingsStore.getState().setTheme('light'))
    await waitFor(() =>
      expect(m.received.at(-1)).toMatchObject({
        event: 'theme.changed',
        data: { '--bg': expect.any(String) }
      })
    )
    m.rerender({ policy, settings: { refresh: 'daily' }, deps: m.deps })
    await waitFor(() =>
      expect(m.received.at(-1)).toEqual({
        v: 1,
        event: 'settings.changed',
        data: { refresh: 'daily' }
      })
    )
    useSettingsStore.getState().setTheme('dark')
  })

  it('announces a project switch as project.changed', async () => {
    const m = mount()
    m.send(readyRequest)
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'))
    act(() => useWorkspaceStore.setState({ project: { id: 'p2', name: 'P2' } }))
    await waitFor(() =>
      expect(m.received.at(-1)).toEqual({
        v: 1,
        event: 'project.changed',
        data: { projectId: 'p2' }
      })
    )
  })

  it('a policy prop change reaches the host without a remount', async () => {
    const m = mount()
    m.send(readyRequest)
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'))
    m.rerender({
      policy: { ...policy, blocked: true, enabled: false },
      settings: { refresh: 'hourly' },
      deps: m.deps
    })
    m.send({ v: 1, id: 'r2', method: 'graph.getFocus', params: {} })
    await waitFor(() =>
      expect(m.received.at(-1)).toMatchObject({ id: 'r2', ok: false, error: { code: 'blocked' } })
    )
    // Still the same host: ready survived the policy update.
    expect(screen.getByTestId('ready').textContent).toBe('true')
  })

  it('tears down on unmount: no listener, no events, host disposed', async () => {
    const m = mount()
    m.send(readyRequest)
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'))
    const before = m.received.length
    m.unmount()
    m.send({ v: 1, id: 'r9', method: 'graph.getFocus', params: {} })
    act(() => useSettingsStore.getState().setTheme('light'))
    await act(async () => undefined)
    await new Promise((r) => setTimeout(r, 10))
    expect(m.received.length).toBe(before)
    expect(m.deps.graph.focusedEntity).not.toHaveBeenCalled()
    useSettingsStore.getState().setTheme('dark')
  })
})
