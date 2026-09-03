// SOLUSDEV-235 / EXT-13 — the icon asset read: route, bearer, type + size caps, misses → null.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { fetchExtensionIconSvg, useExtensionIconSvg } from './extensionIconAsset'

const SVG = '<svg viewBox="0 0 16 16"><path d="M0 0h16v16H0z"/></svg>'

function response(body: string, type = 'image/svg+xml', status = 200): Response {
  return new Response(body, { status, headers: { 'content-type': type } })
}

describe('fetchExtensionIconSvg', () => {
  it('GETs the assets route with the session bearer and returns the text', async () => {
    const fetchImpl = vi.fn(async () => response(SVG))
    const svg = await fetchExtensionIconSvg('bom', '1.2.0', 'icons/page.svg', {
      fetchImpl,
      getToken: async () => 'tok'
    })
    expect(svg).toBe(SVG)
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toMatch(/\/extensions\/bom\/versions\/1\.2\.0\/assets\/icons\/page\.svg$/)
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok')
  })

  it.each([
    ['404', response('', 'image/svg+xml', 404)],
    ['wrong type', response(SVG, 'text/html')],
    ['over the icon cap', response(`<svg>${'x'.repeat(17 * 1024)}</svg>`)]
  ])('returns null on %s', async (_label, res) => {
    expect(
      await fetchExtensionIconSvg('bom', '1.2.0', 'i.svg', {
        fetchImpl: async () => res,
        getToken: async () => null
      })
    ).toBeNull()
  })

  it('returns null when the network throws', async () => {
    expect(
      await fetchExtensionIconSvg('bom', '1.2.0', 'i.svg', {
        fetchImpl: async () => {
          throw new TypeError('offline')
        },
        getToken: async () => null
      })
    ).toBeNull()
  })
})

function Probe({
  version,
  icon
}: {
  version: string | null
  icon: string | null
}): React.JSX.Element {
  const svg = useExtensionIconSvg('bom', version, icon, {
    fetchImpl: async () => response(SVG),
    getToken: async () => null
  })
  return <span data-testid="svg">{svg ?? 'none'}</span>
}

describe('useExtensionIconSvg', () => {
  it('loads for a registry version and never fetches for dev or a missing icon', async () => {
    const { rerender } = render(<Probe version="1.2.0" icon="i.svg" />)
    await waitFor(() => expect(screen.getByTestId('svg').textContent).toBe(SVG))
    rerender(<Probe version="dev" icon="i.svg" />)
    expect(screen.getByTestId('svg').textContent).toBe('none')
    rerender(<Probe version="1.2.0" icon={null} />)
    expect(screen.getByTestId('svg').textContent).toBe('none')
  })
})
