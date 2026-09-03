// SOLUSDEV-235 / EXT-05 — the extension invoke channel names, in ONE module
// (the orb-overlay lesson): main/extensions/extensionsIpc.ts registers them,
// preload/index.ts invokes them.
export const EXT_CHANNELS = {
  index: 'ext:index',
  install: 'ext:install',
  uninstall: 'ext:uninstall',
  devLoad: 'ext:dev:load',
  devRemove: 'ext:dev:remove',
  windowOpen: 'ext:window:open',
  netFetch: 'ext:net:fetch'
} as const
