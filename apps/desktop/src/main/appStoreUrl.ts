// Guard for vendor App Store URLs opened in the system browser (SOLUSDEV-168).
// Pure + side-effect free so it is unit-testable without booting Electron —
// the billingUrl.ts shape, with its own host allowlist.
//
// Why a channel at all: a hosted MCP add-on cannot be subscribed to
// programmatically. Onshape's public API has no purchase-creating operation and
// its Billing guide's only path is a browser redirect scoped to the *calling
// app's own* products — which Solus is not the publisher of. So the user has to
// be sent to the vendor's store, and there was no channel for that:
// `billing:open-external` is host-locked to Stripe, and `oauth:connector:await`
// demands a state and binds the loopback server.

/** Vendor App Store hosts a hosted server's registry `subscribe_url` may name.
 *  The URL comes from our own API, but constraining scheme + host closes the
 *  residual phishing vector if the renderer is ever compromised (CLAUDE.md §7)
 *  — the same reason billing keeps its own list rather than opening whatever it
 *  is handed. The next hosted vendor is one entry here. */
const APP_STORE_HOSTS = new Set(['cad.onshape.com'])

/**
 * True only for an https URL on a known vendor App Store host.
 *
 * Exact hostnames in a Set, deliberately NOT `endsWith('.onshape.com')`: this
 * is an ENTRY point that sends a human somewhere to spend money, so it takes
 * the narrow `isAllowedCheckoutEntryUrl` shape rather than the wide
 * `isAllowedBillingUrl` one, for the reason recorded there — a subdomain is not
 * automatically a place we are willing to send someone to pay.
 */
export function isAllowedAppStoreUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'https:' && APP_STORE_HOSTS.has(parsed.hostname)
  } catch {
    return false
  }
}
