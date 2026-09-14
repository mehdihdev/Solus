import { describe, it, expect, vi, beforeEach } from 'vitest'

// Fake just enough of Electron's BrowserWindow to drive navigation events,
// session permission handlers, and window-open handling.
const { openExternal, FakeBrowserWindow } = vi.hoisted(() => {
  type Handler = (...args: unknown[]) => void
  class FakeSession {
    permissionRequestHandler: ((...args: unknown[]) => void) | null = null
    permissionCheckHandler: (() => boolean) | null = null

    setPermissionRequestHandler(fn: (...args: unknown[]) => void): void {
      this.permissionRequestHandler = fn
    }

    setPermissionCheckHandler(fn: () => boolean): void {
      this.permissionCheckHandler = fn
    }
  }
  class FakeWebContents {
    handlers = new Map<string, Handler[]>()
    windowOpenHandler: ((details: { url: string }) => { action: string }) | null = null
    session = new FakeSession()

    on(event: string, fn: Handler): void {
      this.handlers.set(event, [...(this.handlers.get(event) ?? []), fn])
    }

    setWindowOpenHandler(fn: (details: { url: string }) => { action: string }): void {
      this.windowOpenHandler = fn
    }

    emit(event: string, ...args: unknown[]): void {
      for (const fn of this.handlers.get(event) ?? []) fn(...args)
    }
  }
  class FakeBrowserWindow {
    static instances: FakeBrowserWindow[] = []
    webContents = new FakeWebContents()
    focused = false
    title: string
    private closedHandlers: Handler[] = []
    private destroyed = false
    loadedUrl: string | null = null

    constructor(public options: Record<string, unknown>) {
      FakeBrowserWindow.instances.push(this)
      this.title = String(options.title ?? '')
    }

    on(event: string, fn: Handler): void {
      if (event === 'closed') this.closedHandlers.push(fn)
    }

    loadURL(url: string): Promise<void> {
      this.loadedUrl = url
      return Promise.resolve()
    }

    setTitle(title: string): void {
      this.title = title
    }

    focus(): void {
      this.focused = true
    }

    isDestroyed(): boolean {
      return this.destroyed
    }

    close(): void {
      this.destroyed = true
      for (const fn of this.closedHandlers) fn()
    }
  }
  return { openExternal: vi.fn(), FakeBrowserWindow }
})
vi.mock('electron', () => ({ BrowserWindow: FakeBrowserWindow, shell: { openExternal } }))

import { openCheckoutWindow, isCheckoutWindow } from './checkoutWindow'
import type { BrowserWindow } from 'electron'

const CHECKOUT_URL = 'https://checkout.stripe.com/c/pay/cs_test_abc'
const SUCCESS_URL = 'http://localhost:5173/#/billing?checkout=success'

function lastWindow(): InstanceType<typeof FakeBrowserWindow> {
  const win = FakeBrowserWindow.instances.at(-1)
  if (!win) throw new Error('no window created')
  return win
}

beforeEach(() => {
  openExternal.mockClear()
  FakeBrowserWindow.instances.length = 0
})

describe('openCheckoutWindow', () => {
  registerCheckoutSecurityTests()
  registerCheckoutCompletionTests()
  registerCheckoutPopupsTests()
})

function registerCheckoutSecurityTests(): void {
  it('refuses non-Stripe URLs without opening a window', async () => {
    await expect(openCheckoutWindow('https://evil.example.com/pay')).resolves.toEqual({
      status: 'blocked'
    })
    expect(FakeBrowserWindow.instances).toHaveLength(0)
  })

  it('refuses attacker-creatable Stripe surfaces (buy.stripe.com Payment Links)', async () => {
    await expect(openCheckoutWindow('https://buy.stripe.com/test_abc')).resolves.toEqual({
      status: 'blocked'
    })
    expect(FakeBrowserWindow.instances).toHaveLength(0)
  })

  it('opens a fully sandboxed window in its own throwaway session', async () => {
    const pending = openCheckoutWindow(CHECKOUT_URL)
    const win = lastWindow()
    expect(win.loadedUrl).toBe(CHECKOUT_URL)
    expect(win.options.webPreferences).toMatchObject({
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      partition: 'checkout',
      webviewTag: false
    })
    expect(isCheckoutWindow(win as unknown as BrowserWindow)).toBe(true)
    win.close()
    await pending
  })

  it('denies every permission request and check on its session', async () => {
    const pending = openCheckoutWindow(CHECKOUT_URL)
    const win = lastWindow()
    const callback = vi.fn()
    win.webContents.session.permissionRequestHandler?.(null, 'media', callback)
    expect(callback).toHaveBeenCalledWith(false)
    expect(win.webContents.session.permissionCheckHandler?.()).toBe(false)
    win.close()
    await pending
  })

  it('shows the current origin as the title and ignores page-supplied titles', async () => {
    const pending = openCheckoutWindow(CHECKOUT_URL)
    const win = lastWindow()
    expect(win.title).toBe('Secure checkout — checkout.stripe.com')
    win.webContents.emit(
      'did-navigate',
      { preventDefault: vi.fn() },
      'https://bank.example.com/3ds'
    )
    expect(win.title).toBe('Secure checkout — bank.example.com')
    const titleEvent = { preventDefault: vi.fn() }
    win.webContents.emit('page-title-updated', titleEvent, 'Totally Legit Bank')
    expect(titleEvent.preventDefault).toHaveBeenCalled()
    win.close()
    await pending
  })
}

function registerCheckoutCompletionTests(): void {
  it('closes itself and resolves success on the marker redirect', async () => {
    const pending = openCheckoutWindow(CHECKOUT_URL)
    const win = lastWindow()
    const event = { preventDefault: vi.fn() }
    win.webContents.emit('will-redirect', event, SUCCESS_URL)
    expect(event.preventDefault).toHaveBeenCalled() // the return URL never loads
    await expect(pending).resolves.toEqual({ status: 'success' })
    expect(win.isDestroyed()).toBe(true)
  })

  it('resolves cancel on the cancel marker via client navigation', async () => {
    const pending = openCheckoutWindow(CHECKOUT_URL)
    const win = lastWindow()
    win.webContents.emit(
      'will-navigate',
      { preventDefault: vi.fn() },
      'http://localhost:5173/#/billing?checkout=cancel'
    )
    await expect(pending).resolves.toEqual({ status: 'cancel' })
  })

  it('does NOT close on 3DS / bank hops without a marker', async () => {
    const pending = openCheckoutWindow(CHECKOUT_URL)
    const win = lastWindow()
    const event = { preventDefault: vi.fn() }
    win.webContents.emit('will-navigate', event, 'https://bank.example.com/3ds?txid=1')
    expect(event.preventDefault).not.toHaveBeenCalled()
    expect(win.isDestroyed()).toBe(false)
    win.close()
    await expect(pending).resolves.toEqual({ status: 'closed' })
  })

  it('resolves closed when the user dismisses the window', async () => {
    const pending = openCheckoutWindow(CHECKOUT_URL)
    lastWindow().close()
    await expect(pending).resolves.toEqual({ status: 'closed' })
  })

  it('a second call while one is open focuses it and reports busy', async () => {
    const pending = openCheckoutWindow(CHECKOUT_URL)
    const first = lastWindow()
    await expect(openCheckoutWindow(CHECKOUT_URL)).resolves.toEqual({ status: 'busy' })
    expect(FakeBrowserWindow.instances).toHaveLength(1)
    expect(first.focused).toBe(true)
    first.close()
    await pending
    // After it closes, a new checkout can open again.
    const next = openCheckoutWindow(CHECKOUT_URL)
    expect(FakeBrowserWindow.instances).toHaveLength(2)
    lastWindow().close()
    await next
  })
}

function registerCheckoutPopupsTests(): void {
  describe('popup links (setWindowOpenHandler)', () => {
    it('opens parsed https Stripe links in the system browser and denies the popup', async () => {
      const pending = openCheckoutWindow(CHECKOUT_URL)
      const win = lastWindow()
      const decision = win.webContents.windowOpenHandler?.({ url: 'https://stripe.com/legal' })
      expect(decision).toEqual({ action: 'deny' })
      expect(openExternal).toHaveBeenCalledWith('https://stripe.com/legal')
      win.close()
      await pending
    })

    it.each([
      'https://evil.example.com/phish', // non-Stripe https
      'http://stripe.com/legal', // downgrade
      'file:///etc/passwd',
      'ms-msdt:/id?PCWDiagnostic', // protocol-handler smuggling
      'https://stripe.com.evil.com/x', // lookalike host
      'https://' // malformed despite the prefix
    ])('never hands %s to the OS browser', async (popup) => {
      const pending = openCheckoutWindow(CHECKOUT_URL)
      const win = lastWindow()
      const decision = win.webContents.windowOpenHandler?.({ url: popup })
      expect(decision).toEqual({ action: 'deny' })
      expect(openExternal).not.toHaveBeenCalled()
      win.close()
      await pending
    })

    it('stops opening after the per-window cap', async () => {
      const pending = openCheckoutWindow(CHECKOUT_URL)
      const win = lastWindow()
      for (let i = 0; i < 10; i++) {
        win.webContents.windowOpenHandler?.({ url: 'https://stripe.com/legal' })
      }
      expect(openExternal).toHaveBeenCalledTimes(3)
      win.close()
      await pending
    })
  })
}
