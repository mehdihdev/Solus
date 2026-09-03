// SOLUSDEV-235 / EXT-13 — the page header's icon: the manifest's
// `views.page.icon` SVG text, read through the registry's assets route
// (API.md §2.17 / extensions.md §4.5) and handed to ExtensionIcon, which
// reduces it before anything reaches the DOM. The renderer cannot read
// `solus-ext://` itself (main registers the scheme with `supportFetchAPI:
// false` — the bridge is the frame's only way out, and the same closure keeps
// the renderer out), so a developer registration has no icon source here and
// gets the neutral tile. The fetch lives HERE, beside resources.extensions'
// raw routes, never in a component.
import { useEffect, useState } from 'react'
import { MANIFEST_LIMITS } from '@solus/shared-types'
import { apiBaseUrl, apiToken, joinUrl } from '../../../lib/api/client'
import { extensionAssetUrl } from '../../../lib/api/resources.extensions'

export interface IconAssetTransport {
  readonly fetchImpl?: typeof fetch
  readonly getToken?: () => Promise<string | null>
}

/** The SVG text, or null for any miss (404, wrong type, over the contract's
 *  16 KiB icon cap, network). A missing icon is a tile, never an error. */
export async function fetchExtensionIconSvg(
  slug: string,
  version: string,
  iconPath: string,
  transport: IconAssetTransport = {}
): Promise<string | null> {
  const fetchImpl = transport.fetchImpl ?? globalThis.fetch
  try {
    const token = await (transport.getToken ?? apiToken)()
    const res = await fetchImpl(joinUrl(apiBaseUrl, extensionAssetUrl(slug, version, iconPath)), {
      headers: {
        Accept: 'image/svg+xml',
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      }
    })
    if (!res.ok || !(res.headers.get('content-type') ?? '').includes('svg')) return null
    const text = await res.text()
    return text.length > MANIFEST_LIMITS.iconBytes ? null : text
  } catch {
    return null
  }
}

interface LoadedIcon {
  readonly key: string
  readonly svg: string | null
}

/** Null until loaded, and null when there is nothing to load (dev, no icon). */
export function useExtensionIconSvg(
  slug: string,
  version: string | null,
  iconPath: string | null,
  transport?: IconAssetTransport
): string | null {
  const key =
    version === null || version === 'dev' || iconPath === null
      ? null
      : `${slug}/${version}/${iconPath}`
  const [loaded, setLoaded] = useState<LoadedIcon | null>(null)
  useEffect(() => {
    if (key === null || version === null || iconPath === null) return
    let cancelled = false
    void fetchExtensionIconSvg(slug, version, iconPath, transport).then((svg) => {
      if (!cancelled) setLoaded({ key, svg })
    })
    return () => {
      cancelled = true
    }
  }, [key, slug, version, iconPath, transport])
  return loaded !== null && loaded.key === key ? loaded.svg : null
}
