// SOLX-02: the sol-window invoke channel names, in ONE module (the orb-overlay
// lesson — a renamed literal compiles clean on both sides). main/index.ts
// registers the handlers; preload/index.ts exposes the invokes. The ratchet in
// solWindow.test.ts keeps stray literals out of main/ and preload/.
export const SOL_WINDOW_CHANNELS = {
  detach: 'sol-window:detach',
  attach: 'sol-window:attach'
} as const
