// In-app Stripe Checkout / billing-portal window (SOLUSDEV-114): checkout is
// self-contained in a sandboxed child window instead of a browser tab. When
// Stripe redirects to one of our marker return URLs the navigation is blocked,
// the window closes itself, and the caller gets the outcome — entitlement still
// only ever comes from the webhook, never from this signal.
import { BrowserWindow, shell } from 'electron'
import { classifyCheckoutNavigation } from './checkoutReturn'
import { isAllowedBillingUrl, isAllowedCheckoutEntryUrl } from './billingUrl'

export type CheckoutStatus = 'success' | 'cancel' | 'return' | 'closed' | 'blocked' | 'busy'

const CHECKOUT_WINDOW = { width: 500, height: 760 } as const

// In-memory session partition (no `persist:` prefix): Stripe/3DS cookies,
// storage, and service workers never touch the app's default session and
// vanish when the app quits (sec review M1).
const CHECKOUT_PARTITION = 'checkout'

// Popup budget per window: legit checkout links (terms, privacy) are one or
// two clicks; a hostile page must not flood the user's browser (sec review H2).
const MAX_POPUP_OPENS = 3

// Windows opened by this module — lets index.ts skip dev shortcuts (F12
// devtools) on remote content (sec review L4).
const checkoutWindows = new WeakSet<BrowserWindow>()

export function isCheckoutWindow(win: BrowserWindow): boolean {
  return checkoutWindows.has(win)
}

// One checkout at a time: a second request focuses the open window instead of
// stacking new ones (sec review M3 — the renderer `busy` flag is UI-only).
let activeWindow: BrowserWindow | null = null

/** Spoof-resistant origin indicator: the title always shows the CURRENT host
 *  (3DS hops included) and never a page-supplied string (sec review M2). */
function checkoutTitle(url: string): string {
  try {
    return `Secure checkout — ${new URL(url).host}`
  } catch {
    return 'Secure checkout'
  }
}

/** Open a Stripe-hosted URL in a sandboxed child window and resolve with how it
 *  ended: a marker redirect (success/cancel/return) or the user closing it. */
export function openCheckoutWindow(
  url: string,
  parent?: BrowserWindow
): Promise<{ status: CheckoutStatus }> {
  // Entry allowlist is the NARROW one — buy.stripe.com Payment Links are
  // attacker-creatable and must never render as our checkout.
  if (!isAllowedCheckoutEntryUrl(url)) return Promise.resolve({ status: 'blocked' })
  if (activeWindow && !activeWindow.isDestroyed()) {
    activeWindow.focus()
    return Promise.resolve({ status: 'busy' })
  }
  return new Promise((resolve) => {
    const win = new BrowserWindow({
      ...CHECKOUT_WINDOW,
      parent,
      title: checkoutTitle(url),
      autoHideMenuBar: true,
      // Remote Stripe content: full sandbox, no preload, no Node access, its
      // own throwaway session, no <webview>.
      webPreferences: {
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false,
        partition: CHECKOUT_PARTITION,
        webviewTag: false
      }
    })
    checkoutWindows.add(win)
    activeWindow = win
    // Remote content gets no device/permission grants, ever: no camera, mic,
    // geolocation, notifications, clipboard-read (sec review M1).
    win.webContents.session.setPermissionRequestHandler((_wc, _permission, callback) =>
      callback(false)
    )
    win.webContents.session.setPermissionCheckHandler(() => false)
    win.webContents.on('will-attach-webview', (event) => event.preventDefault())
    // The title tracks the frame's real origin; page-chosen titles are ignored.
    win.webContents.on('page-title-updated', (event) => event.preventDefault())
    win.webContents.on('did-navigate', (_event, target: string) => {
      if (!win.isDestroyed()) win.setTitle(checkoutTitle(target))
    })

    let outcome: CheckoutStatus | null = null
    const onNavigate = (event: { preventDefault: () => void }, target: string): void => {
      const result = classifyCheckoutNavigation(target)
      if (result === null) return // ordinary checkout navigation (incl. 3DS hops)
      event.preventDefault() // the return URL never actually loads
      outcome = result
      if (!win.isDestroyed()) win.close()
    }
    // will-redirect catches Stripe's server-side 303 to the return URL;
    // will-navigate catches client-side location changes.
    win.webContents.on('will-redirect', onNavigate)
    win.webContents.on('will-navigate', onNavigate)

    // Links inside checkout (terms, privacy) open in the system browser — but
    // only parsed https Stripe URLs, and only a few per window (sec review H2).
    let popupOpens = 0
    win.webContents.setWindowOpenHandler(({ url: popup }) => {
      if (popupOpens < MAX_POPUP_OPENS && isAllowedBillingUrl(popup)) {
        popupOpens += 1
        void shell.openExternal(popup)
      }
      return { action: 'deny' }
    })

    win.on('closed', () => {
      activeWindow = null
      resolve({ status: outcome ?? 'closed' })
    })
    void win.loadURL(url)
  })
}
