// SOLUSDEV-252 S3: the SOL window channel names, in ONE module (the orb-overlay
// lesson — a renamed literal compiles clean on both sides). main/index.ts
// registers the invokes and pushes; preload/solBridge.ts exposes them. The
// ratchet in solWindow.test.ts keeps stray `sol:` literals out of main/ and
// preload/.
export const SOL_WINDOW_CHANNELS = {
  open: 'sol:open',
  getState: 'sol:get-state',
  guideTarget: 'sol:guide-target',
  setMode: 'sol:set-mode',
  setScreenIntelligence: 'sol:set-screen-intelligence',
  setHotkeys: 'sol:set-hotkeys',
  /** SOLUSDEV-318: open the OS pane the capture capability names. No argument —
   *  main opens its own capability's settingsUrl, never a renderer-supplied one. */
  openCaptureSettings: 'sol:open-capture-settings',
  /** SOLUSDEV-319: the pill's measured content height (it grows upward). */
  resize: 'sol:resize',
  /** SOLUSDEV-319: busy pills (streaming, approval parked, plan running) ignore blur. */
  setBusy: 'sol:set-busy',
  /** SOLUSDEV-319: Esc hides the pill; the window and its thread live on. */
  hide: 'sol:hide',
  /** SOLUSDEV-319 drive slice 3 (sol-drive.md §5): Settings › SOL "SOL can use
   *  your mouse and keyboard" — status, the setting, `trust --prompt`. */
  getDriveStatus: 'sol:get-drive-status',
  setDrive: 'sol:set-drive',
  requestDrivePermissions: 'sol:request-drive-permissions',
  /** Slice 3b: open System Settings › Login Items (the agent needs approval). */
  openDriveApproval: 'sol:open-drive-approval',
  /** The renderer says a drive.step is running (true) or ended (false). */
  setDriving: 'sol:set-driving',
  /** main → the app's renderers: the DriveStatus on every change. */
  driveStatus: 'sol:drive-status',
  /** SOLUSDEV-319 main → the SOL window only: the pill's motion cues —
   *  `summoned` (with `resume`: same chat kept) after a show, `leaving` just
   *  before main hides it (the renderer plays its exit animation). */
  pill: 'sol:pill',
  /** main → every app renderer: the SolState snapshot. */
  state: 'sol:state',
  /** main → the SOL window only: a captured region. */
  region: 'sol:region',
  /** SOLUSDEV-319 slice 4 (sol-drive.md §2.2) main → the SOL window only: the
   *  front-app summon snapshot (`SolFrontApp | null`), on every change. */
  frontApp: 'sol:front-app'
} as const

/** SOLUSDEV-319: a re-summon within this long of a hide resumes the same
 *  conversation in the same place; after it, a fresh pill at the cursor. */
export const SOL_PILL_RESUME_MS = 5000
/** SOLUSDEV-319: how long main waits for the renderer's exit animation before
 *  hiding the window (bounded, so a dead renderer cannot keep it up). */
export const SOL_PILL_EXIT_MS = 180
