// SOLUSDEV-236 — Enterprise "Contact sales" opens the user's mail client.
//
// A bare mailto: anchor does nothing because externalUrl.ts only lets https
// out (SOLUSDEV-235 H2, unchanged). This channel opens ONE fixed mailto from
// main and takes no URL from the renderer, so it cannot become a general opener.

export const CONTACT_SALES_MAILTO = 'mailto:team@solusforge.com?subject=Enterprise%20plan'

export interface ContactSalesDeps {
  /** e.g. `(url) => shell.openExternal(url)`. */
  open: (url: string) => Promise<void>
  /** True only for the app's own main renderer (senderGate.ts). */
  isTrustedSender: () => boolean
}

/** Open the sales mailto. Refuses foreign senders; never throws. */
export async function openContactSales(deps: ContactSalesDeps): Promise<{ ok: boolean }> {
  if (!deps.isTrustedSender()) return { ok: false }
  try {
    await deps.open(CONTACT_SALES_MAILTO)
    return { ok: true }
  } catch {
    return { ok: false }
  }
}
