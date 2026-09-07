// SOLUSDEV-246 / STORE ST4 — first-party pages rendered IN-REPO.
//
// A community bundle's page is a sandboxed frame (ADR-035). A first-party
// bundle's page cannot be: its data lives behind the bundle's own backend
// routes (`/projects/{id}/widgets/<slug>/…`), which the bridge deliberately
// cannot reach. So a first-party page is trusted React in this repo, keyed by
// the bundle's slug, using the typed API client like any other screen. The
// rail entry, install, enablement and team block are still the install row's:
// the shell only picks the renderer, and only for an INSTALLED entry whose
// PINNED manifest declares a first-party table (the publish gate restricts those
// tables to Solus staff) — a community bundle that happens to carry the slug
// still gets the sandboxed frame.
// Adding a first-party page is adding one line here plus its feature folder.
import { createElement, type ComponentType, type ReactElement } from 'react'
import { BomScreen } from '../bom/BomScreen'

export interface FirstPartyPageProps {
  readonly projectId: string
  readonly slug: string
  /** The install row's publisher — the header never hardcodes one. */
  readonly publisher: { readonly displayName: string; readonly verified: boolean } | null
  readonly onBack?: () => void
  readonly onOpenStore?: () => void
}

export const FIRST_PARTY_PAGES: Readonly<Record<string, ComponentType<FirstPartyPageProps>>> = {
  bom: BomScreen
}

export function hasFirstPartyPage(slug: string): boolean {
  return Object.hasOwn(FIRST_PARTY_PAGES, slug)
}

/** The in-repo page for `slug`, or null when the bundle has none. */
export function renderFirstPartyPage(
  slug: string,
  props: FirstPartyPageProps
): ReactElement | null {
  if (!hasFirstPartyPage(slug)) return null
  return createElement(FIRST_PARTY_PAGES[slug], props)
}
