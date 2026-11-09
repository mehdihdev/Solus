// SOLUSDEV-323: the main window's size per screen. Signed out it is a compact
// starter (460 wide) that swaps in place for sign-in / create-account, then
// grows into onboarding or the workspace; signing out shrinks it back. The
// renderer only names a size — main owns the bounds and validates everything.
// No electron import: preload reads the channel and types from here too.

export type WindowSize = 'starter' | 'auth' | 'full'
export type CompactSize = Exclude<WindowSize, 'full'>

export const WINDOW_SIZE_CHANNEL = 'window:size'

export const COMPACT_SIZES: Readonly<Record<CompactSize, { width: number; height: number }>> = {
  starter: { width: 460, height: 640 },
  auth: { width: 460, height: 800 }
}

/** The workspace's minimum, restored only once the window has grown past it. */
export const FULL_MIN = { width: 900, height: 600 } as const

/** Upper bound on waiting for macOS to report the end of an animated resize. */
const DEFAULT_SETTLE_MS = 900
/** Upper bound on waiting for macOS to leave full screen before shrinking. */
const FULL_SCREEN_EXIT_MS = 1500

const HEX_COLOUR = /^#[0-9a-f]{6}$/i

export interface WindowSizeRequest {
  size: WindowSize
  /** false under reduced motion: jump instead of animating. */
  animate?: boolean
  /** The theme's --bg, painted behind the page so a growing edge never flashes. */
  background?: string
}

export interface Rect {
  x: number
  y: number
  width: number
  height: number
}

function isWindowSize(value: unknown): value is WindowSize {
  return value === 'starter' || value === 'auth' || value === 'full'
}

/** Validate an untrusted renderer payload; unknown extras are dropped. */
export function parseWindowSizeRequest(raw: unknown): WindowSizeRequest | null {
  if (typeof raw !== 'object' || raw === null) return null
  const { size, animate, background } = raw as Record<string, unknown>
  if (!isWindowSize(size)) return null
  return {
    size,
    ...(typeof animate === 'boolean' ? { animate } : {}),
    ...(typeof background === 'string' && HEX_COLOUR.test(background) ? { background } : {})
  }
}

/** A `size` rect with the same centre as `around`, kept inside `work`. */
export function centredRect(
  around: Rect,
  size: { width: number; height: number },
  work: Rect
): Rect {
  const width = Math.min(size.width, work.width)
  const height = Math.min(size.height, work.height)
  const cx = around.x + around.width / 2
  const cy = around.y + around.height / 2
  const clamp = (v: number, lo: number, hi: number): number => Math.min(Math.max(v, lo), hi)
  return {
    x: Math.round(clamp(cx - width / 2, work.x, work.x + work.width - width)),
    y: Math.round(clamp(cy - height / 2, work.y, work.y + work.height - height)),
    width,
    height
  }
}

type SizerEvent = 'resized' | 'leave-full-screen'

/** The slice of BrowserWindow the sizer drives (a fake in tests). */
export interface SizableWindow {
  getBounds(): Rect
  setBounds(bounds: Rect, animate?: boolean): void
  setMinimumSize(width: number, height: number): void
  setResizable(resizable: boolean): void
  setMaximizable(maximizable: boolean): void
  setFullScreenable(fullScreenable: boolean): void
  isMaximized(): boolean
  unmaximize(): void
  isFullScreen(): boolean
  setFullScreen(flag: boolean): void
  isVisible(): boolean
  isDestroyed(): boolean
  setBackgroundColor(colour: string): void
  once(event: SizerEvent, listener: () => void): void
  removeListener(event: SizerEvent, listener: () => void): void
}

export interface WindowSizerDeps {
  platform: string
  /** The work area of the display the window is on. */
  workArea: (bounds: Rect) => Rect
  /** Full size when none is remembered (first launch signed out). */
  defaultFull: () => { width: number; height: number }
  settleMs?: number
}

/** The smallest compact size: one minimum for both, so starter → auth never snaps. */
const COMPACT_MIN = COMPACT_SIZES.starter

const sameRect = (a: Rect, b: Rect): boolean =>
  a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height

export class WindowSizer {
  private current: WindowSize = 'full'
  private fullSize: { width: number; height: number } | null = null
  private queue: Promise<void> = Promise.resolve()
  private latest = 0

  constructor(
    private readonly win: SizableWindow,
    private readonly deps: WindowSizerDeps
  ) {}

  get size(): WindowSize {
    return this.current
  }

  /**
   * Requests run in order, so a quick sign-in → sign-out never interleaves.
   * A compact request already superseded by a newer one is dropped (latest
   * wins), so clicking back and forth never queues a string of animations.
   */
  apply(request: WindowSizeRequest): Promise<void> {
    const seq = ++this.latest
    const run = (): Promise<void> =>
      request.size !== 'full' && seq !== this.latest ? Promise.resolve() : this.run(request)
    // A failed resize must never wedge every later one.
    this.queue = this.queue.then(run).catch(() => undefined)
    return this.queue
  }

  private async run({ size, animate = true, background }: WindowSizeRequest): Promise<void> {
    if (size === this.current || this.win.isDestroyed()) return
    if (background) this.win.setBackgroundColor(background)
    if (this.win.isFullScreen()) {
      // Growing: full screen already is full. Shrinking: leave it first.
      if (size === 'full') {
        this.current = size
        return
      }
      this.win.setFullScreen(false)
      await this.waitFor('leave-full-screen', FULL_SCREEN_EXIT_MS)
      animate = false
    }
    if (size !== 'full') this.lockCompact()
    await this.resizeTo(this.targetFor(size), animate)
    if (size === 'full') this.unlockFull()
    this.current = size
  }

  private targetFor(size: WindowSize): Rect {
    const bounds = this.win.getBounds()
    const wanted =
      size === 'full' ? (this.fullSize ?? this.deps.defaultFull()) : COMPACT_SIZES[size]
    return centredRect(bounds, wanted, this.deps.workArea(bounds))
  }

  /** macOS animates natively (smooth, compositor-driven); elsewhere it jumps. */
  private async resizeTo(target: Rect, animate: boolean): Promise<void> {
    if (this.win.isDestroyed() || sameRect(this.win.getBounds(), target)) return
    const native = animate && this.deps.platform === 'darwin' && this.win.isVisible()
    const settled = native ? this.waitFor('resized', this.deps.settleMs ?? DEFAULT_SETTLE_MS) : null
    this.win.setBounds(target, native)
    await settled
  }

  private lockCompact(): void {
    if (this.current === 'full') {
      const { width, height } = this.win.getBounds()
      const maximized = this.win.isMaximized()
      this.fullSize = maximized ? null : { width, height }
      if (maximized) this.win.unmaximize()
    }
    // Never above the screen: a minimum taller than a small laptop pushes it off.
    const work = this.deps.workArea(this.win.getBounds())
    this.win.setMinimumSize(
      Math.min(COMPACT_MIN.width, work.width),
      Math.min(COMPACT_MIN.height, work.height)
    )
    this.win.setResizable(false)
    this.win.setMaximizable(false)
    this.win.setFullScreenable(false)
  }

  // Restored after the grow: a 900 px minimum on a 460 px window would snap it.
  private unlockFull(): void {
    if (this.win.isDestroyed()) return
    this.win.setMinimumSize(FULL_MIN.width, FULL_MIN.height)
    this.win.setResizable(true)
    this.win.setMaximizable(true)
    this.win.setFullScreenable(true)
  }

  /** Resolve on `event` or after `ms`, whichever is first; safe if the window dies. */
  private waitFor(event: SizerEvent, ms: number): Promise<void> {
    return new Promise((resolve) => {
      const done = (): void => {
        clearTimeout(timer)
        if (!this.win.isDestroyed()) this.win.removeListener(event, done)
        resolve()
      }
      const timer = setTimeout(done, ms)
      this.win.once(event, done)
    })
  }
}

interface SizeEvent {
  sender: unknown
}

export interface WindowSizeHandlerDeps<E extends SizeEvent> {
  /** Only the main window's own renderer may resize it. */
  isMainSender: (event: E) => boolean
  sizer: () => WindowSizer | null
  /** The first accepted size releases the reveal gate. */
  onSized: () => void
}

/** The `window:size` IPC handler: sender first, then the payload, then the sizer. */
export function createWindowSizeHandler<E extends SizeEvent>(
  deps: WindowSizeHandlerDeps<E>
): (event: E, raw: unknown) => Promise<boolean> {
  return async (event, raw) => {
    if (!deps.isMainSender(event)) return false
    const request = parseWindowSizeRequest(raw)
    const sizer = deps.sizer()
    if (!request || !sizer) return false
    await sizer.apply(request)
    deps.onSized()
    return true
  }
}

/**
 * Show the window only once the page has painted AND its first size is
 * applied, so a signed-out launch never flashes full-size and then shrinks.
 * `waitMs` bounds the wait for a size that never comes.
 */
export function createRevealGate(
  show: () => void,
  waitMs: number
): { ready: () => void; sized: () => void } {
  let isReady = false
  let isSized = false
  let shown = false
  const reveal = (): void => {
    if (shown) return
    shown = true
    show()
  }
  return {
    ready: () => {
      isReady = true
      if (isSized) reveal()
      else setTimeout(reveal, waitMs)
    },
    sized: () => {
      isSized = true
      if (isReady) reveal()
    }
  }
}
