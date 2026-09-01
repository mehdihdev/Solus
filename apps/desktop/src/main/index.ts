import { app, shell, dialog, BrowserWindow, ipcMain } from 'electron'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'
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
import { isAllowedCheckoutEntryUrl } from './billingUrl'
import {
  readChatCache,
  realSolChatCacheDeps,
  removeChatCache,
  writeChatCache
} from './solChatCache'
import { openCheckoutWindow, isCheckoutWindow } from './checkoutWindow'
import { isFromWindow } from './senderGate'
import { createSolBrowserWindow, registerSolWindowHandlers } from './sol-window/solWindow'

/** Open a Stripe Checkout / billing-portal URL in the system browser, refusing
 *  anything that isn't one of the Stripe-hosted surfaces our API returns
 *  (see billingUrl.ts — buy.stripe.com Payment Links are attacker-creatable). */
async function openBillingUrl(url: string): Promise<{ ok: boolean }> {
  if (!isAllowedCheckoutEntryUrl(url)) return { ok: false }
  await shell.openExternal(url)
  return { ok: true }
}

// The app's own renderer window — the only legitimate sender for privileged
// IPC (billing), and the parent for the checkout window.
let mainWindow: BrowserWindow | null = null

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
}

/** The machine-local SOL chat cache (~/.solus, ADR-034 Layer 1 — SOLUSDEV-233).
 *  Ids and sizes are re-validated inside solChatCache; content is an opaque
 *  JSON string the renderer owns. */
function registerSolChatCacheHandlers(): void {
  const isString = (v: unknown): v is string => typeof v === 'string'
  ipcMain.handle('solchat:read', (event, projectId: unknown, conversationId: unknown) =>
    isMainRendererSender(event) && isString(projectId) && isString(conversationId)
      ? readChatCache(projectId, conversationId, realSolChatCacheDeps)
      : null
  )
  ipcMain.handle(
    'solchat:write',
    (event, projectId: unknown, conversationId: unknown, content: unknown) => ({
      ok:
        isMainRendererSender(event) &&
        isString(projectId) &&
        isString(conversationId) &&
        isString(content)
          ? writeChatCache(projectId, conversationId, content, realSolChatCacheDeps)
          : false
    })
  )
  ipcMain.handle('solchat:remove', (event, projectId: unknown, conversationId: unknown) => ({
    ok:
      isMainRendererSender(event) && isString(projectId) && isString(conversationId)
        ? removeChatCache(projectId, conversationId, realSolChatCacheDeps)
        : false
  }))
}

/** True when the invoke came from the app's own renderer, not some other
 *  webContents that gained IPC reach. The decision itself lives in
 *  `senderGate.ts`, where it can be tested. */
function isMainRendererSender(event: Electron.IpcMainInvokeEvent): boolean {
  return isFromWindow(event.sender, mainWindow)
}

function createWindow(): void {
  // Create the browser window.
  mainWindow = new BrowserWindow({
    width: 900,
    height: 670,
    show: false,
    autoHideMenuBar: true,
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
    if (mainWindow === win) mainWindow = null
  })

  win.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

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
    // Set app user model id for windows
    electronApp.setAppUserModelId('com.electron')

    // Default open or close DevTools by F12 in development
    // and ignore CommandOrControl + R in production.
    // see https://github.com/alex8088/electron-toolkit/tree/master/packages/utils
    app.on('browser-window-created', (_, window) => {
      // Never wire dev shortcuts (F12 devtools) onto windows showing remote
      // content (the Stripe checkout window) — app windows only.
      if (!isCheckoutWindow(window)) optimizer.watchWindowShortcuts(window)
    })

    // Local project folder (SOLUSDEV-164): pick an existing directory, clone a
    // repo into a chosen parent, or reveal a linked folder in the OS file manager.
    // The clone input is untrusted renderer data — cloneRepo validates it.
    ipcMain.handle('folder:pick', async () => {
      const result = await dialog.showOpenDialog({
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

    registerFolderRegistryHandlers()
    registerSolChatCacheHandlers()

    // Billing (SOLUSDEV-83 follow-up): open a Stripe-hosted Checkout / billing
    // portal URL (returned by our API) in the system browser. Only the app's
    // own renderer may invoke either billing channel.
    ipcMain.handle('billing:open-external', (event, url: string) =>
      isMainRendererSender(event) ? openBillingUrl(url) : { ok: false }
    )
    // Billing (SOLUSDEV-114): self-contained checkout — same Stripe URL, but in
    // a sandboxed in-app window that closes itself on the return redirect.
    ipcMain.handle('billing:open-checkout', (event, url: string) =>
      isMainRendererSender(event)
        ? openCheckoutWindow(url, mainWindow ?? undefined)
        : { status: 'blocked' }
    )

    // Detached SOL orb (SOLX-02): the always-on-top second window at #/orb.
    // The renderer initiates both directions over these invokes; the CTR-06
    // orb↔overlay wire is attached to the window at creation.
    registerSolWindowHandlers(ipcMain, () => createSolBrowserWindow(ipcMain), isMainRendererSender)

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

    // Local bridge companion (BRG-04): spawn/supervise, and relay the renderer's
    // Supabase access token over stdin. Renderer input is untrusted — accept
    // only a string token or null (signout); never log it. Only the app's own
    // renderer may relay a token (credential-bearing, like bridge:license — L2).
    ipcMain.handle('bridge:token', (event, token: unknown) => {
      if (isMainRendererSender(event) && (typeof token === 'string' || token === null)) {
        sendAccessToken(token)
      }
    })
    // The project the companion serves. The bridge route is project-scoped, so
    // without this the companion has no URL to dial and stays idle. Renderer
    // input is untrusted: a string or null only, and companionWsUrl refuses any
    // id that is not a single safe path segment.
    ipcMain.handle('bridge:project', (event, projectId: unknown) => {
      if (isMainRendererSender(event) && (typeof projectId === 'string' || projectId === null)) {
        setCompanionProject(projectId)
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
