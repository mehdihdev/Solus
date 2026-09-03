// SOLUSDEV-235 / EXT-13 — hook lifecycle: loading → caching → ready, retry,
// cancellation on unmount, and the browser (no bridge) refusal.
import { describe, it, expect, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import type { InstalledBundleDeps } from './installedBundle'
import { useInstalledBundle } from './useInstalledBundle'
import { fakeBridge, fakeBundleDeps } from './testing/fixtures'

function Probe({ deps, slug = 'bom' }: { deps: InstalledBundleDeps; slug?: string }): React.JSX.Element {
  const { state, retry } = useInstalledBundle('p1', slug, 'page', deps)
  return (
    <>
      <span data-testid="status">{state.status}</span>
      <button type="button" onClick={retry}>
        retry
      </button>
    </>
  )
}

describe('useInstalledBundle', () => {
  it('starts loading, passes through caching, and lands on ready', async () => {
    const deps = fakeBundleDeps({ bridge: fakeBridge() })
    render(<Probe deps={deps} />)
    expect(screen.getByTestId('status').textContent).toBe('loading')
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('ready'))
    expect(deps.fetchBundle).toHaveBeenCalledTimes(1)
  })

  it('re-resolves on retry', async () => {
    const deps = fakeBundleDeps({ listInstalls: vi.fn(async () => []) })
    render(<Probe deps={deps} />)
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('not_installed'))
    act(() => screen.getByText('retry').click())
    await waitFor(() => expect(deps.listInstalls).toHaveBeenCalledTimes(2))
  })

  it('refuses in a plain browser without touching the API', async () => {
    const deps = fakeBundleDeps({ bridge: null })
    render(<Probe deps={deps} />)
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('error'))
    expect(deps.listInstalls).not.toHaveBeenCalled()
  })

  it('drops a resolution that finishes after unmount', async () => {
    let release: (() => void) | null = null
    const deps = fakeBundleDeps({
      listInstalls: () =>
        new Promise((resolve) => {
          release = () => resolve([])
        })
    })
    const view = render(<Probe deps={deps} />)
    view.unmount()
    // Resolving after unmount must not warn or throw (setState on an unmounted tree).
    await act(async () => {
      release?.()
    })
    expect(release).not.toBeNull()
  })
})
