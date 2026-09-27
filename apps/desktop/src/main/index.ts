import { findNativeGuideTarget, readNativeWindowProperty } from './sol-window/nativeGuideTarget'
import {
  app,
  shell,
  dialog,
  BrowserWindow,
  globalShortcut,
  ipcMain,
  Menu,
  nativeImage,
  protocol,
  screen,
  systemPreferences,
  Tray,
  type NativeImage
} from 'electron'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'
import dockIcon from '../../build/icon.png?asset'
import {
  awaitGithubCallback,
  awaitOAuthCallback,
  cancelActiveOAuth,
  getConnectorRedirectUrl,
  getRedirectUrl
} from './oauthLoopback'
import {
  notifyProjectFolderChanged,
  startCompanion,
  stopCompanion,
  sendAccessToken,
  setCompanionProject,
  writeCredential
} from './companion'
import { cloneRepo, cloneDeps, vscodeFolderUrl, type CloneInput } from './projectFolder'
import {
  folderLinkInput,
  linkProjectFolder,
  readRegistry,
  realLocalStateDeps,
  unlinkProjectFolder
} from './localState'
import { machineIdentity, realMachineIdentityDeps } from './machineIdentity'
import { isAllowedAppStoreUrl } from './appStoreUrl'
import { isAllowedCheckoutEntryUrl } from './billingUrl'
import { realSolChatCacheDeps, solChatCacheIpc } from './solChatCache'
import { preferencesIpc, realPreferencesStoreDeps } from './preferencesStore'
import { HardwareLocalStore } from './hardwareLocalState'
import { HardwareSources, authorizeHardwareScope, readHardwareSource } from './hardwareSources'
import { resolveApiBaseUrl } from '../renderer/src/lib/cspConnect'
import { openCheckoutWindow, isCheckoutWindow } from './checkoutWindow'
import { isFromWindow } from './senderGate'
import { externalOpenHandler } from './externalUrl'
import {
  createSolBrowserWindow,
  createSolWindowManager,
  registerSolIpcHandlers,
  type SolState,
  type SolWindowManager
} from './sol-window/solWindow'
import { createSolSettings } from './solSettings'
import { createScreenCapture, realScreenCaptureDeps, type Rect } from './capture/screenCapture'
import { createTray, paintDot, type SolTray } from './tray'
import { detectPlatformBasics, staticCapabilities } from './platform/capabilities'
import { enableShortcutPortal } from './hotkeys/globalHotkeys'
import { startHotkeys, type HotkeysHandle, type HotkeyStatus, type KeyHookLoad } from './hotkeys'
import { realExtensionFs } from './extensions/extensionFs'
import {
  createExtProtocolHandler,
  EXT_SCHEME,
  EXT_SCHEME_PRIVILEGES
} from './extensions/extProtocol'
import {
  closeExtensionWindowsOnSignOut,
  createExtensionBrowserWindow,
  createExtensionWindowManager,
  type ExtensionWindowManager
} from './extensions/extensionWindow'
import { createExtensionsIpc, registerExtensionsIpc } from './extensions/extensionsIpc'
import { realNetProxyDeps } from './extensions/netProxy'
import { mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { pathToFileURL } from 'node:url'
import { bootDiagnostics, resolveSentryConfig } from './diagnostics/boot'
import { isAppRendererUrl } from './diagnostics/diagnosticsIpc'
import { loadSentrySink } from './diagnostics/sentrySink'

// SOLUSDEV-311: error reporting first — crash handlers are live before
// anything below can throw (docs/architecture/desktop-error-handling.md).
const diagnostics = bootDiagnostics({
  app,
  proc: process,
  ipcMain,
  showErrorBox: (title, body) => dialog.showErrorBox(title, body),
  homeDir: homedir(),
  isDev: is.dev,
  ensureDir: (path) => mkdirSync(path, { recursive: true }),
  loadSentry: loadSentrySink,
  sentry: resolveSentryConfig(process.env, import.meta.env, is.dev)
})

enableShortcutPortal(
  app.commandLine,
  detectPlatformBasics(process.env, process.platform, process.arch)
)

// Extensions (SOLUSDEV-235 / ADR-035 §1): the read-only solus-ext:// origin the
// sandboxed frames load their bundles from. A privileged scheme MUST be declared
// before app ready; the handler is installed after (see whenReady below).
protocol.registerSchemesAsPrivileged([{ scheme: EXT_SCHEME, privileges: EXT_SCHEME_PRIVILEGES }])

/** Open a Stripe Checkout / billing-portal URL in the system browser, refusing
 *  anything that isn't one of the Stripe-hosted surfaces our API returns
 *  (see billingUrl.ts — buy.stripe.com Payment Links are attacker-creatable). */
async function openBillingUrl(url: string): Promise<{ ok: boolean }> {
  if (!isAllowedCheckoutEntryUrl(url)) return { ok: false }
  await shell.openExternal(url)
  return { ok: true }
}

/** SOLUSDEV-168: a hosted MCP add-on's vendor App Store page. Its own narrow
 *  host allowlist rather than a reuse of the billing one — different vendor,
 *  different trust decision, and neither should widen the other. */
async function openAppStoreUrl(url: string): Promise<{ ok: boolean }> {
  if (!isAllowedAppStoreUrl(url)) return { ok: false }
  await shell.openExternal(url)
  return { ok: true }
}

// The app's own renderer window — the only legitimate sender for privileged
// IPC (billing), and the parent for the checkout window.
let mainWindow: BrowserWindow | null = null
// Extension windows (SOLUSDEV-235): closed on sign-out and with the main window.
let extensionWindows: ExtensionWindowManager | null = null
let hardwareSources: HardwareSources | null = null
// SOL window / tray / hotkeys (SOLUSDEV-252 S3): torn down on before-quit.
let solWindows: SolWindowManager | null = null
let solTray: SolTray | null = null
let hotkeys: HotkeysHandle | null = null

/**
 * The ~/.solus project registry (SOLUSDEV-166 / ADR-034): the durable
 * machine-local project→folder links the companion's workspace derives from.
 * All three channels carry private machine paths, so — like billing and
 * bridge — only the app's own renderer may invoke them. Inputs are untrusted:
 * folderLinkInput picks only the known fields, and linkProjectFolder
 * re-validates id and path before any write. A successful link/unlink of the
 * ACTIVE project respawns the companion so SOLUS_COMPANION_WORKSPACE picks up
 * the change.
 */
function registerFolderRegistryHandlers(): void {
  ipcMain.handle('folder:link', (event, projectId: unknown, link: unknown) => {
    if (!isMainRendererSender(event) || typeof projectId !== 'string') return { ok: false }
    const input = folderLinkInput(link)
    if (input === null) return { ok: false }
    const ok = linkProjectFolder(projectId, input, realLocalStateDeps)
    if (ok) notifyProjectFolderChanged(projectId)
    return { ok }
  })
  ipcMain.handle('folder:unlink', (event, projectId: unknown) => {
    if (!isMainRendererSender(event) || typeof projectId !== 'string') return { ok: false }
    const ok = unlinkProjectFolder(projectId, realLocalStateDeps)
    if (ok) notifyProjectFolderChanged(projectId)
    return { ok }
  })
  ipcMain.handle('folder:links', (event) =>
    isMainRendererSender(event) ? readRegistry(realLocalStateDeps).registry.projects : {}
  )
  // This machine's identity for local-folder sources (SOLUSDEV-249): the
  // companion's instance id (~/.solus/companion_id, created here the same way
  // when the desktop runs first) plus the hostname. An unwritable home yields
  // null — the renderer then says the folder cannot be linked to the graph.
  ipcMain.handle('folder:machine', (event) => {
    if (!isMainRendererSender(event)) return null
    try {
      return machineIdentity(realMachineIdentityDeps)
    } catch {
      return null
    }
  })
}

/** The machine-local SOL chat cache (~/.solus, ADR-034 Layer 1 — SOLUSDEV-233).
 *  Ids and sizes are re-validated inside solChatCache; content is an opaque
 *  JSON string the renderer owns. */
function registerSolChatCacheHandlers(): void {
  const deps = realSolChatCacheDeps
  ipcMain.handle('solchat:read', (event, projectId: unknown, conversationId: unknown) =>
    solChatCacheIpc.read(isMainRendererSender(event), projectId, conversationId, deps)
  )
  ipcMain.handle(
    'solchat:write',
    (event, projectId: unknown, conversationId: unknown, content: unknown) =>
      solChatCacheIpc.write(isMainRendererSender(event), projectId, conversationId, content, deps)
  )
  ipcMain.handle('solchat:remove', (event, projectId: unknown, conversationId: unknown) =>
    solChatCacheIpc.remove(isMainRendererSender(event), projectId, conversationId, deps)
  )
  ipcMain.handle('solchat:clear', (event) =>
    solChatCacheIpc.clear(isMainRendererSender(event), deps)
  )
}

/** The user's engineering preferences, ~/.solus/preferences.json (ADR-034 as
 *  amended 2026-09-06 — SOLUSDEV-244 / HOME H3). Shape, caps and the
 *  newer-schema rule are enforced inside preferencesStore; the renderer's copy
 *  is re-parsed there, never trusted. */
function registerPreferencesHandlers(): void {
  const deps = realPreferencesStoreDeps
  ipcMain.handle('prefs:read', (event) => preferencesIpc.read(isMainRendererSender(event), deps))
  ipcMain.handle('prefs:write', (event, document: unknown) =>
    preferencesIpc.write(isMainRendererSender(event), document, deps)
  )
}

/** Private source authority stays in MAIN. The renderer gets portable references;
 * membership is independently verified against the configured API for each operation. */
function registerHardwareSourceHandlers(): void {
  const sources = new HardwareSources({
    store: new HardwareLocalStore(app.getPath('home')),
    authorize: (token, projectId, signal) =>
      authorizeHardwareScope(
        token,
        projectId,
        signal,
        resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL)
      ),
    readFile: readHardwareSource,
    pickFile: async () => {
      if (mainWindow === null) return null
      const picked = await dialog.showOpenDialog(mainWindow, {
        title: 'Choose hardware configuration',
        properties: ['openFile', 'dontAddToRecent'],
        filters: [
          { name: 'Hardware configuration', extensions: ['json', 'yaml', 'yml', 'toml', 'py'] }
        ]
      })
      return picked.canceled || picked.filePaths.length !== 1 ? null : picked.filePaths[0]
    },
    confirmDigestChange: async ({ displayName, previousDigest, contentSha256 }) => {
      if (mainWindow === null) return false
      const result = await dialog.showMessageBox(mainWindow, {
        type: 'question',
        title: 'Review changed hardware configuration',
        message: `Use the changed ${displayName}?`,
        detail: `Previous SHA-256: ${previousDigest}\nSelected SHA-256: ${contentSha256}\nThe changed contents require a new hardware proposal before they can be applied.`,
        buttons: ['Cancel', 'Use selected file'],
        defaultId: 0,
        cancelId: 0,
        noLink: true
      })
      return result.response === 1
    }
  })
  hardwareSources = sources
  const allowed = (event: Electron.IpcMainInvokeEvent): boolean =>
    isMainRendererSender(event) && event.senderFrame === mainWindow?.webContents.mainFrame
  ipcMain.handle('hardware:sources:list', (event) => sources.list(allowed(event)))
  ipcMain.handle('hardware:sources:pick', (event, input: unknown) =>
    sources.pick(allowed(event), input)
  )
  ipcMain.handle('hardware:sources:recheck', (event, input: unknown) =>
    sources.recheck(allowed(event), input)
  )
}

/** Extensions (SOLUSDEV-235 / EXT-05, ADR-035): serve installed bundles + dev
 *  folders read-only over solus-ext://, and wire the install / dev-mode /
 *  window / network-proxy invokes. Every channel is sender-gated; every
 *  decision (ids, hashes, sizes, origins, addresses) lives in main/extensions
 *  where it is unit-tested against injected fs/net surfaces. Called after app
 *  ready — the scheme itself is declared privileged at module load above. */
function registerExtensionHandlers(): void {
  protocol.handle(EXT_SCHEME, createExtProtocolHandler(realExtensionFs))
  const windows = createExtensionWindowManager(createExtensionBrowserWindow)
  extensionWindows = windows
  registerExtensionsIpc(
    ipcMain,
    {
      isMainRenderer: isMainRendererSender,
      // SEC-M3: extension windows host the same trusted renderer and need the
      // runtime channels; the manager admits only windows it created.
      isExtensionWindow: (event) => windows.isSender(event.sender)
    },
    createExtensionsIpc({ fs: realExtensionFs, net: realNetProxyDeps, windows })
  )
}

/** True when the invoke came from the app's own renderer, not some other
 *  webContents that gained IPC reach. The decision itself lives in
 *  `senderGate.ts`, where it can be tested. */
function isMainRendererSender(event: Electron.IpcMainInvokeEvent): boolean {
  return isFromWindow(event.sender, mainWindow)
}

/** The Solus renderer's own URL base: the dev server, or the packaged index.html. */
function rendererBase(): string {
  const devUrl = process.env['ELECTRON_RENDERER_URL']
  return is.dev && devUrl ? devUrl : pathToFileURL(join(__dirname, '../renderer/index.html')).href
}

/** Diagnostics admit any Solus app window (main, SOL, overlay, extension host —
 *  one bundle) from its top frame, never the checkout window, a subframe, or a
 *  page that navigated away. */
function isAppWindowSender(event: { sender: unknown; senderFrame?: unknown }): boolean {
  const contents = event.sender as Electron.WebContents
  const win = BrowserWindow.fromWebContents(contents)
  return (
    win !== null &&
    !isCheckoutWindow(win) &&
    event.senderFrame === contents.mainFrame &&
    isAppRendererUrl(contents.getURL(), rendererBase())
  )
}

/** The SOL channels admit the main renderer OR the SOL window's own renderer
 *  (the same trusted bundle at #/sol-window); the checkout window stays out. */
function isSolSender(event: Electron.IpcMainInvokeEvent): boolean {
  return isMainRendererSender(event) || (solWindows?.isSender(event.sender) ?? false)
}

const TRAY_ICON_PX = 22

/** What the hook loader answers while the setting is off: no hook, and the
 *  status line says why (§7 — the consent surface for a global keyboard hook). */
const HOTKEYS_OFF: KeyHookLoad = {
  hook: null,
  state: { status: 'unavailable', message: 'Hold-Ctrl gestures are turned off in Settings.' }
}

/**
 * SOL window, screen capture, tray and global hotkeys (SOLUSDEV-252 S3 —
 * docs/architecture/sol-window.md §2, §6, §7; wireflow §A, §E). Settings →
 * capture → window manager → tray → hotkeys. Every platform-touching piece
 * degrades with a plain-language message rather than throwing: the app must
 * boot on a box with no hook, no indicator host and no capture.
 */
let guideScopeGeneration = 0
let guideSignedIn = false
let guideProject: string | null = null
function startSol(): void {
  const basics = detectPlatformBasics(process.env, process.platform, process.arch)
  const settings = createSolSettings(realLocalStateDeps)
  const capture = createScreenCapture({
    ...realScreenCaptureDeps(basics),
    // §7 "off means no capture ever": gated inside captureRegion, not per caller.
    isEnabled: () => settings.get().screenIntelligence
  })
  let hotkeyStatus: HotkeyStatus | null = null
  let lastRegionRefused = false
  const state = (): SolState => {
    const { actionMode, screenIntelligence, hotkeys: hotkeysEnabled, alwaysOnTop } = settings.get()
    return {
      actionMode,
      screenIntelligence,
      hotkeysEnabled,
      alwaysOnTop,
      capture: capture.capability(),
      hotkeys: hotkeyStatus,
      lastRegionRefused
    }
  }
  const windows = createAppSolWindows(settings)
  solWindows = windows
  const publish = (): void => {
    const snapshot = state()
    windows.pushState(snapshot)
    solTray?.update(snapshot)
  }
  let hotkeysOn = settings.get().hotkeys
  settings.onChange((next) => {
    guideScopeGeneration += 1
    if (next.screenIntelligence) lastRegionRefused = false
    if (next.hotkeys !== hotkeysOn) {
      hotkeysOn = next.hotkeys
      runHotkeys()
    }
    publish()
  })
  registerSolIpcHandlers(
    ipcMain,
    {
      windows,
      settings,
      state,
      guideScope: () => (guideSignedIn && guideProject ? guideScopeGeneration : null),
      guideTarget: () =>
        findNativeGuideTarget({
          session: basics.session,
          displays: screen
            .getAllDisplays()
            .map((display) => ({ id: String(display.id), bounds: display.bounds })),
          read: readNativeWindowProperty
        })
    },
    isSolSender
  )

  startSolTray(basics, settings, windows)

  // A closed loop: capture (setting on) → open + region; setting off → the
  // capture answers `disabled` and the window opens with the one-line refusal
  // (§7 "off means no capture ever"). Nothing pixel-shaped is logged or persisted.
  const onRegion = async (region: Rect): Promise<void> => {
    const result = await capture.captureRegion(region)
    windows.open()
    if ('reason' in result) {
      lastRegionRefused = result.reason === 'disabled'
      if (!lastRegionRefused) console.warn(`[sol] region capture skipped: ${result.reason}`)
      publish()
      return
    }
    lastRegionRefused = false
    publish()
    windows.pushRegion({
      pngBase64: result.png.toString('base64'),
      contextPngBase64: result.contextPng.toString('base64'),
      width: result.width,
      height: result.height,
      source: result.window,
      capturedAt: Date.now()
    })
  }

  // Boot and every flip of the hotkeys setting go through here: stop what runs,
  // then start again — with no hook at all while the setting is off.
  function runHotkeys(): void {
    restartSolHotkeys(basics, settings, windows, onRegion, (status) => {
      hotkeyStatus = status
      publish()
    })
  }

  runHotkeys()
  publish()
}

/** Preferred main-window size, clamped to the primary display's work area so a
 *  small laptop screen still gets a window that fits. */
const PREFERRED_WINDOW = { width: 1440, height: 900 } as const
const WINDOW_SCREEN_MARGIN = 40

function initialWindowSize(): { width: number; height: number } {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize
  return {
    width: Math.min(PREFERRED_WINDOW.width, width - WINDOW_SCREEN_MARGIN),
    height: Math.min(PREFERRED_WINDOW.height, height - WINDOW_SCREEN_MARGIN)
  }
}

function createWindow(): void {
  // Create the browser window.
  mainWindow = new BrowserWindow({
    ...initialWindowSize(),
    minWidth: 900,
    minHeight: 600,
    show: false,
    autoHideMenuBar: true,
    // SOLUSDEV-235: the renderer owns the title row (project pill), so on macOS the
    // native bar collapses to the traffic lights, vertically centred in that 44px row.
    ...(process.platform === 'darwin'
      ? { titleBarStyle: 'hiddenInset' as const, trafficLightPosition: { x: 16, y: 16 } }
      : {}),
    ...(process.platform === 'linux' ? { icon } : {}),
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false
    }
  })
  const win = mainWindow

  win.on('ready-to-show', () => {
    win.show()
  })
  win.on('closed', () => {
    if (mainWindow === win) {
      mainWindow = null
      hardwareSources?.setToken(null)
      hardwareSources?.setProject(null)
    }
    // No main window → no session to host an extension bridge under.
    extensionWindows?.closeAll()
  })

  // Renderer anchors reach the OS browser only over https (SOLUSDEV-235 / H2).
  win.webContents.setWindowOpenHandler(externalOpenHandler((url) => shell.openExternal(url)))

  // HMR for renderer base on electron-vite cli.
  // Load the remote URL for development or the local html file for production.
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    win.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

// Single instance (SOLUSDEV-154 / BRG-04): the companion supervisor assumes
// exactly one owner per user (pidfile takeover). A second launch hands off to
// the first and quits.
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const win = BrowserWindow.getAllWindows()[0]
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
    }
  })

  // This method will be called when Electron has finished
  // initialization and is ready to create browser windows.
  // Some APIs can only be used after this event occurs.
  app.whenReady().then(() => {
    // Windows taskbar identity — must match electron-builder's appId, not the
    // scaffold's 'com.electron' leftover (SOLUSDEV-233 logo work).
    electronApp.setAppUserModelId('com.solusforge.solus')

    // macOS DEV dock: without this the dock shows the Electron binary's own
    // icon — resources/icon.png only feeds Linux windows and packaged builds
    // (which get theirs from build/icon.png via electron-builder).
    if (process.platform === 'darwin') app.dock?.setIcon(dockIcon)

    // Default open or close DevTools by F12 in development
    // and ignore CommandOrControl + R in production.
    // see https://github.com/alex8088/electron-toolkit/tree/master/packages/utils
    app.on('browser-window-created', (_, window) => {
      // Never wire dev shortcuts (F12 devtools) onto windows showing remote
      // content (the Stripe checkout window) — app windows only.
      if (!isCheckoutWindow(window)) optimizer.watchWindowShortcuts(window)
    })

    diagnostics.registerIpc({
      isAppSender: isAppWindowSender,
      isMainSender: (event) =>
        isFromWindow(event.sender, mainWindow) &&
        event.senderFrame === mainWindow?.webContents.mainFrame
    })

    registerProjectFolderHandlers()

    registerFolderRegistryHandlers()
    registerSolChatCacheHandlers()
    registerPreferencesHandlers()
    registerHardwareSourceHandlers()

    registerExtensionHandlers()

    registerBillingHandlers()

    // The SOL window, tray and hotkeys (SOLUSDEV-252 S3); the window is the
    // CTR-06 host — the orb↔overlay wire is attached to it at creation.
    startSol()

    registerOAuthHandlers()

    registerCompanionHandlers()

    startCompanion()

    createWindow()

    app.on('activate', function () {
      // On macOS it's common to re-create a window in the app when the
      // dock icon is clicked and there are no other windows open.
      if (BrowserWindow.getAllWindows().length === 0) createWindow()
    })
  })

  // Tear the companion's process tree down before quitting: hold the quit once,
  // stop (SIGTERM → 3 s grace → SIGKILL), then resume it.
  let companionStopped = false
  app.on('before-quit', (event) => {
    hotkeys?.stop()
    hotkeys = null
    solTray?.destroy()
    solTray = null
    if (companionStopped) return
    companionStopped = true
    event.preventDefault()
    void stopCompanion().finally(() => app.quit())
  })
}

// Quit when all windows are closed, except on macOS. There, it's common
// for applications and their menu bar to stay active until the user quits
// explicitly with Cmd + Q.
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

// In this file you can include the rest of your app's specific main process
// code. You can also put them in separate files and require them here.

function startSolTray(
  basics: ReturnType<typeof detectPlatformBasics>,
  settings: ReturnType<typeof createSolSettings>,
  windows: SolWindowManager
): void {
  // Tray: the mark at tray size, and the same mark with the sees-screen dot.
  const trayOff = nativeImage
    .createFromPath(icon)
    .resize({ width: TRAY_ICON_PX, height: TRAY_ICON_PX })
  const size = trayOff.getSize()
  const trayOn = nativeImage.createFromBitmap(
    paintDot(trayOff.toBitmap(), size.width, size.height),
    size
  )
  solTray = createTray({
    basics,
    env: process.env,
    icons: { off: trayOff, on: trayOn },
    createTray: (image) => new Tray(image as NativeImage),
    buildMenu: (template) => Menu.buildFromTemplate(template),
    onOpen: () => windows.open(),
    onSetMode: (mode) => settings.setMode(mode),
    onSetScreenIntelligence: (on) => settings.setScreenIntelligence(on),
    onSetHotkeys: (on) => settings.setHotkeys(on),
    onQuit: () => app.quit(),
    warn: (message) => console.warn(message)
  })
}

function restartSolHotkeys(
  basics: ReturnType<typeof detectPlatformBasics>,
  settings: ReturnType<typeof createSolSettings>,
  windows: SolWindowManager,
  onRegion: (region: Rect) => Promise<void>,
  onStatus: (status: HotkeyStatus) => void
): void {
  hotkeys?.stop()
  hotkeys = null
  try {
    hotkeys = startHotkeys({
      capabilities: staticCapabilities(basics),
      globalShortcut,
      getCursor: () => screen.getCursorScreenPoint(),
      displayFor: (point) => screen.getDisplayNearestPoint(point),
      now: Date.now,
      scheduler: { setInterval, clearInterval },
      ...(settings.get().hotkeys ? {} : { loadHook: () => HOTKEYS_OFF }),
      ...(process.platform === 'darwin'
        ? {
            isTrustedAccessibilityClient: () =>
              systemPreferences.isTrustedAccessibilityClient(false)
          }
        : {}),
      onSummon: () => windows.open(),
      onToggleMode: () => void settings.toggleMode(),
      onRegion: (region) => void onRegion(region),
      onStatus,
      // SOLUS_DEBUG_GESTURE=1: cursor samples + evaluations (coordinates only).
      ...(process.env['SOLUS_DEBUG_GESTURE']
        ? { debug: (line: string) => console.warn(`[gesture] ${line}`) }
        : {})
    })
  } catch (error) {
    console.warn(`[sol] hotkeys unavailable: ${error instanceof Error ? error.message : 'unknown'}`)
  }
}

function registerProjectFolderHandlers(): void {
  // Local project folder (SOLUSDEV-164): pick an existing directory, clone a
  // repo into a chosen parent, or reveal a linked folder in the OS file manager.
  // The clone input is untrusted renderer data — cloneRepo validates it.
  ipcMain.handle('folder:pick', async () => {
    const result = await dialog.showOpenDialog({
      title: 'Select a project folder',
      buttonLabel: 'Select this folder',
      properties: ['openDirectory', 'createDirectory']
    })
    return result.canceled || result.filePaths.length === 0 ? null : result.filePaths[0]
  })
  ipcMain.handle('folder:reveal', async (_event, path: string) => {
    const error = await shell.openPath(path)
    return { ok: error === '' }
  })
  // Open the linked folder in VSCode via its vscode://file URL scheme. The
  // path is untrusted renderer data — vscodeFolderUrl validates and encodes
  // it; openExternal rejects when no vscode:// handler is installed.
  ipcMain.handle('folder:open-vscode', async (_event, path: unknown) => {
    const url = typeof path === 'string' ? vscodeFolderUrl(path) : null
    if (!url) return { ok: false }
    try {
      await shell.openExternal(url)
      return { ok: true }
    } catch {
      return { ok: false }
    }
  })
  ipcMain.handle('git:clone', (_event, input: CloneInput) => cloneRepo(input, cloneDeps))
}

function registerBillingHandlers(): void {
  // Billing (SOLUSDEV-83 follow-up): open a Stripe-hosted Checkout / billing
  // portal URL (returned by our API) in the system browser. Only the app's
  // own renderer may invoke either billing channel.
  ipcMain.handle('billing:open-external', (event, url: string) =>
    isMainRendererSender(event) ? openBillingUrl(url) : { ok: false }
  )
  // Hosted MCP add-ons (SOLUSDEV-168): send the user to the vendor's App
  // Store to subscribe. Sender-gated like every other privileged channel.
  ipcMain.handle('hosted:open-store', (event, url: string) =>
    isMainRendererSender(event) ? openAppStoreUrl(url) : { ok: false }
  )
  // Billing (SOLUSDEV-114): self-contained checkout — same Stripe URL, but in
  // a sandboxed in-app window that closes itself on the return redirect.
  ipcMain.handle('billing:open-checkout', (event, url: string) =>
    isMainRendererSender(event)
      ? openCheckoutWindow(url, mainWindow ?? undefined)
      : { status: 'blocked' }
  )
}

function registerOAuthHandlers(): void {
  // GitHub OAuth (loopback): the renderer asks for the redirect URL, builds the
  // Supabase authorize URL, then hands it back for the system-browser round-trip.
  ipcMain.handle('oauth:github:redirect-url', () => getRedirectUrl())
  ipcMain.handle('oauth:github:await', (_event, authorizeUrl: string) =>
    awaitGithubCallback(authorizeUrl)
  )

  // Connector OAuth (GitHub/GitLab/Onshape/…): a CONSTANT redirect URL, since
  // strict providers match the registered URI exactly. The nonce is the
  // backend's own OAuth state, echoed back by the provider.
  ipcMain.handle('oauth:connector:redirect-url', () => getConnectorRedirectUrl())
  // Sender-gated like the other credential-bearing channels: this one RESOLVES
  // WITH THE AUTHORIZATION CODE, so any other webContents that gained IPC reach
  // could open a provider consent screen and read the code out of the result.
  // The state check inside is a CSRF defence, not a caller check.
  ipcMain.handle('oauth:connector:await', (event, authorizeUrl: string, expectedState: string) =>
    isMainRendererSender(event)
      ? awaitOAuthCallback(authorizeUrl, expectedState)
      : Promise.reject(new Error('unauthorized sender'))
  )
  // Cancel seam (SOLUSDEV-165): closing the connect wizard mid-handshake
  // settles the parked flow now instead of leaving the loopback armed for
  // five minutes. Sender-gated like the await it cancels.
  ipcMain.handle('oauth:connector:cancel', (event) =>
    isMainRendererSender(event)
      ? cancelActiveOAuth()
      : Promise.reject(new Error('unauthorized sender'))
  )
}

function registerCompanionHandlers(): void {
  // Local bridge companion (BRG-04): spawn/supervise, and relay the renderer's
  // Supabase access token over stdin. Renderer input is untrusted — accept
  // only a string token or null (signout); never log it. Only the app's own
  // renderer may relay a token (credential-bearing, like bridge:license — L2).
  // A null token is sign-out: the extension windows go with the session.
  ipcMain.handle('bridge:token', (event, token: unknown) => {
    if (isMainRendererSender(event) && (typeof token === 'string' || token === null)) {
      guideScopeGeneration += 1
      guideSignedIn = typeof token === 'string' && token.length > 0
      sendAccessToken(token)
      hardwareSources?.setToken(token)
      if (extensionWindows) closeExtensionWindowsOnSignOut(extensionWindows, token)
    }
  })
  // The project the companion serves. The bridge route is project-scoped, so
  // without this the companion has no URL to dial and stays idle. Renderer
  // input is untrusted: a string or null only, and companionWsUrl refuses any
  // id that is not a single safe path segment.
  ipcMain.handle('bridge:project', (event, projectId: unknown) => {
    if (isMainRendererSender(event) && (typeof projectId === 'string' || projectId === null)) {
      guideScopeGeneration += 1
      guideProject = projectId
      setCompanionProject(projectId)
      hardwareSources?.setProject(projectId)
    }
  })
  // BYO-license capture (SOLUSDEV-102 / MCP-05): relay license credentials
  // to the companion's stdin. Renderer input is untrusted — writeCredential
  // validates shape; values are never logged, never persisted, and flow
  // renderer → preload → main → child stdin only. Only the app's own
  // renderer may invoke this channel (credential-bearing, like billing).
  ipcMain.handle('bridge:license', (event, server: unknown, secrets: unknown) =>
    isMainRendererSender(event)
      ? writeCredential(server, secrets)
      : { ok: false, error: 'unauthorized sender' }
  )
}

function createAppSolWindows(settings: ReturnType<typeof createSolSettings>): SolWindowManager {
  return createSolWindowManager({
    createWindow: (bounds, alwaysOnTop) =>
      createSolBrowserWindow(
        bounds,
        alwaysOnTop,
        ipcMain,
        process.platform === 'linux' ? icon : undefined
      ),
    screen,
    settings,
    // The main window only (the manager adds the SOL window itself). Never the
    // checkout window (remote Stripe content) nor extension windows (third-party
    // bundles) — sol:state is for the app's own renderers (security M2).
    allWindows: () => (mainWindow ? [mainWindow] : [])
  })
}
