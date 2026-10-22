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
  setAlwaysOnTop: 'sol:set-always-on-top',
  setHotkeys: 'sol:set-hotkeys',
  /** SOLUSDEV-318: open the OS pane the capture capability names. No argument —
   *  main opens its own capability's settingsUrl, never a renderer-supplied one. */
  openCaptureSettings: 'sol:open-capture-settings',
  /** main → every app renderer: the SolState snapshot. */
  state: 'sol:state',
  /** main → the SOL window only: a captured region. */
  region: 'sol:region'
} as const
