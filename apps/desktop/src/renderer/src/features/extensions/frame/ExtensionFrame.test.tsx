// SOLUSDEV-235 / EXT-13 — the sandboxed element, its four render states, the
// 10 s handshake timeout, foreign-message isolation, and the motion classes.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { fakeBridgeDeps } from '../host/testing/fakeBridgeDeps'
import { ExtensionFrame, FRAME_SANDBOX, HANDSHAKE_TIMEOUT_MS } from './ExtensionFrame'
import type { InstalledBundleState, ReadyBundle } from './installedBundle'
import type { InstalledBundle } from './useInstalledBundle'
import { fakeBridge, fakeBundleDeps, fakeInstall, fakeManifest } from './testing/fixtures'

function readyBundle(overrides: Partial<ReadyBundle> = {}): ReadyBundle {
  return {
    status: 'ready',
    policy: {
      extensionId: 'bom',
      version: '1.2.0',
      projectId: 'p1',
      grantedScopes: ['graph.read'],
      grantedNetwork: [],
      enabled: true,
      blocked: false,
      mode: 'page'
    },
    version: '1.2.0',
    manifest: fakeManifest(),
    entry: 'page.html',
    name: 'BOM',
    settings: {},
    publisher: { displayName: 'Solus', verified: true },
    ...overrides
  }
}

function controlled(
  state: InstalledBundleState
): InstalledBundle & { retry: ReturnType<typeof vi.fn> } {
  return { state, retry: vi.fn() }
}

const base = { projectId: 'p1', slug: 'bom', view: 'page' as const }
const readyRequest = { v: 1, id: 'r1', method: 'ui.ready', params: {} }

function frame(): HTMLIFrameElement {
  return screen.getByTestId('extension-frame') as HTMLIFrameElement
}

function sendReady(source: unknown): void {
  fireEvent(
    window,
    new MessageEvent('message', { data: readyRequest, source: source as Window, origin: 'null' })
  )
}

beforeEach(() => {
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'P1' } })
})
afterEach(() => {
  useWorkspaceStore.setState({ project: null })
  vi.useRealTimers()
})

describe('ExtensionFrame element', () => {
  it('renders exactly sandbox="allow-scripts" over a solus-ext URL with no other capability', () => {
    render(
      <ExtensionFrame {...base} bundle={controlled(readyBundle())} bridgeDeps={fakeBridgeDeps()} />
    )
    const el = frame()
    expect(FRAME_SANDBOX).toBe('allow-scripts')
    expect(el.getAttribute('sandbox')).toBe('allow-scripts')
    expect(el.getAttribute('src')).toBe('solus-ext://bom/1.2.0/page.html')
    expect(el.getAttribute('srcdoc')).toBeNull()
    expect(el.hasAttribute('preload')).toBe(false)
    expect(el.getAttribute('allow')).toBe('')
    expect(el.getAttribute('referrerpolicy')).toBe('no-referrer')
    expect(el.getAttribute('title')).toBe('BOM (page)')
  })

  it('stays hidden behind the skeleton until ui.ready, then fades in with .screen-in', async () => {
    const onStateChange = vi.fn()
    render(
      <ExtensionFrame
        {...base}
        bundle={controlled(readyBundle())}
        bridgeDeps={fakeBridgeDeps()}
        onStateChange={onStateChange}
      />
    )
    expect(screen.getByTestId('frame-skeleton')).toHaveTextContent('Loading BOM…')
    expect(screen.getByTestId('frame-skeleton').className).toContain('screen-in')
    expect(frame().style.visibility).toBe('hidden')
    expect(onStateChange).toHaveBeenLastCalledWith('loading')
    sendReady(frame().contentWindow)
    await waitFor(() => expect(frame().style.visibility).toBe('visible'))
    expect(frame().className).toContain('screen-in')
    expect(screen.queryByTestId('frame-skeleton')).toBeNull()
    expect(onStateChange).toHaveBeenLastCalledWith('ready')
  })

  it('ignores ui.ready from any window that is not this frame', async () => {
    render(
      <ExtensionFrame {...base} bundle={controlled(readyBundle())} bridgeDeps={fakeBridgeDeps()} />
    )
    sendReady(window)
    sendReady(null)
    const other = document.createElement('iframe')
    document.body.appendChild(other)
    sendReady(other.contentWindow)
    await act(async () => undefined)
    expect(frame().style.visibility).toBe('hidden')
    expect(screen.getByTestId('frame-skeleton')).toBeInTheDocument()
    other.remove()
  })
})

describe('ExtensionFrame handshake timeout', () => {
  it('is 10 s and turns into an error card that keeps the frame mounted; Reload remounts', () => {
    vi.useFakeTimers()
    const onStateChange = vi.fn()
    render(
      <ExtensionFrame
        {...base}
        bundle={controlled(readyBundle())}
        bridgeDeps={fakeBridgeDeps()}
        onStateChange={onStateChange}
      />
    )
    expect(HANDSHAKE_TIMEOUT_MS).toBe(10_000)
    act(() => vi.advanceTimersByTime(9_999))
    expect(screen.queryByTestId('frame-error')).toBeNull()
    act(() => vi.advanceTimersByTime(1))
    const card = screen.getByTestId('frame-error')
    expect(card).toHaveTextContent("BOM didn't start.")
    expect(card).toHaveTextContent('It did not respond in 10 s.')
    expect(frame().style.visibility).toBe('hidden')
    expect(onStateChange).toHaveBeenLastCalledWith('error')
    act(() => screen.getByRole('button', { name: 'Reload' }).click())
    expect(screen.queryByTestId('frame-error')).toBeNull()
    expect(screen.getByTestId('frame-skeleton')).toBeInTheDocument()
    expect(onStateChange).toHaveBeenLastCalledWith('loading')
  })

  it('shows the failing request path for a dev registration and busts its cache on Reload', () => {
    vi.useFakeTimers()
    const dev = readyBundle({
      version: 'dev',
      policy: { ...readyBundle().policy, version: 'dev', mode: 'dev' }
    })
    render(<ExtensionFrame {...base} bundle={controlled(dev)} bridgeDeps={fakeBridgeDeps()} />)
    expect(frame().getAttribute('src')).toBe('solus-ext://bom/dev/page.html?r=0')
    act(() => vi.advanceTimersByTime(HANDSHAKE_TIMEOUT_MS))
    expect(screen.getByTestId('frame-error')).toHaveTextContent('solus-ext://bom/dev/page.html?r=0')
    act(() => screen.getByRole('button', { name: 'Reload' }).click())
    expect(frame().getAttribute('src')).toBe('solus-ext://bom/dev/page.html?r=1')
  })
})

describe('ExtensionFrame bundle states', () => {
  it('shows the loading and downloading skeletons', () => {
    const { rerender } = render(
      <ExtensionFrame {...base} bundle={controlled({ status: 'loading' })} />
    )
    expect(screen.getByTestId('frame-skeleton')).toHaveTextContent('Loading bom…')
    rerender(<ExtensionFrame {...base} bundle={controlled({ status: 'caching', name: 'BOM' })} />)
    expect(screen.getByTestId('frame-skeleton')).toHaveTextContent('Downloading BOM…')
  })

  it('shows an honest error card with the step and a Retry that re-resolves', () => {
    const bundle = controlled({
      status: 'error',
      step: 'download',
      message: "Couldn't download BOM."
    })
    const onStateChange = vi.fn()
    render(
      <ExtensionFrame
        {...base}
        bundle={bundle}
        onStateChange={onStateChange}
        actions={<button>Open in Store</button>}
      />
    )
    const card = screen.getByTestId('frame-error')
    expect(card).toHaveTextContent("bom didn't start.")
    expect(card).toHaveTextContent("Couldn't download BOM.")
    expect(screen.getByRole('button', { name: 'Open in Store' })).toBeInTheDocument()
    expect(onStateChange).toHaveBeenLastCalledWith('error')
    screen.getByRole('button', { name: 'Retry' }).click()
    expect(bundle.retry).toHaveBeenCalledTimes(1)
  })

  it('shows blocked and disabled states without a frame or a Retry', () => {
    const { rerender } = render(
      <ExtensionFrame {...base} bundle={controlled({ status: 'blocked', name: 'BOM' })} />
    )
    expect(screen.getByTestId('frame-blocked')).toHaveTextContent('Blocked by your team.')
    expect(screen.queryByTestId('extension-frame')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
    rerender(<ExtensionFrame {...base} bundle={controlled({ status: 'disabled', name: 'BOM' })} />)
    expect(screen.getByTestId('frame-disabled')).toHaveTextContent(
      'BOM is disabled in this project.'
    )
    expect(screen.queryByTestId('extension-frame')).toBeNull()
  })

  it('names the browser refusal and the not-installed case plainly', () => {
    const { rerender } = render(
      <ExtensionFrame
        {...base}
        bundle={controlled({
          status: 'error',
          step: 'no_desktop',
          message: 'Extensions run in the Solus desktop app.'
        })}
      />
    )
    expect(screen.getByTestId('frame-error')).toHaveTextContent(
      'Extensions run in the Solus desktop app.'
    )
    rerender(<ExtensionFrame {...base} bundle={controlled({ status: 'not_installed' })} />)
    expect(screen.getByTestId('frame-error')).toHaveTextContent(
      "bom isn't installed in this project."
    )
  })

  it('resolves on its own when no bundle is passed, downloading through the bridge', async () => {
    const bridge = fakeBridge()
    const deps = fakeBundleDeps({ bridge, listInstalls: async () => [fakeInstall()] })
    render(<ExtensionFrame {...base} bundleDeps={deps} bridgeDeps={fakeBridgeDeps()} />)
    await waitFor(() => expect(screen.getByTestId('extension-frame')).toBeInTheDocument())
    expect(bridge.install).toHaveBeenCalledTimes(1)
    expect(frame().getAttribute('src')).toBe('solus-ext://bom/1.2.0/page.html')
  })
})

describe('ExtensionFrame motion', () => {
  it('relies on the app-wide .screen-in class, which main.css disables under reduced motion', () => {
    const css = readFileSync(resolve(__dirname, '../../../assets/main.css'), 'utf8')
    const reduced = css.split('@media (prefers-reduced-motion: reduce)').slice(1)
    expect(reduced.some((block) => /\.screen-in[\s\S]*?animation:\s*none/.test(block))).toBe(true)
  })
})
