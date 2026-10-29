// SOLUSDEV-319 drive slice 3b (docs/architecture/sol-drive.md §5; ADR-041
// amendment 2026-10-28): the drive agent trusts any process satisfying
// Solus.app's code requirement, so the Electron fuses that keep that process
// running only Solus code are verified by reading them back from the packed
// binary BEFORE signing.
//
// electron-builder 26 flips `electronFuses` after `afterPack` and immediately
// before signing (platformPackager.doAddElectronFuses), so a plain afterPack
// read would see the unflipped binary. This hook therefore flips them itself
// with electron-builder's own helpers (same config, so the later flip is a
// no-op), reads the wire back with @electron/fuses, and throws — failing the
// build — unless every configured fuse matches. Wired as `afterPack` in
// apps/desktop/electron-builder.yml.
'use strict'
const path = require('node:path')

/** The wire's bytes: ASCII '0' / '1' (@electron/fuses FuseState, which its
 *  index does not export). */
const FUSE_STATE = { DISABLE: 48, ENABLE: 49 }

/** electronFuses options that configure the flip, not a fuse. */
const NOT_FUSES = new Set(['resetAdHocDarwinSignature', 'strictlyRequireAllFuses'])

/** electronFuses config key → @electron/fuses FuseV1Options member. */
const FUSE_OPTION = {
  runAsNode: 'RunAsNode',
  enableCookieEncryption: 'EnableCookieEncryption',
  enableNodeOptionsEnvironmentVariable: 'EnableNodeOptionsEnvironmentVariable',
  enableNodeCliInspectArguments: 'EnableNodeCliInspectArguments',
  enableEmbeddedAsarIntegrityValidation: 'EnableEmbeddedAsarIntegrityValidation',
  onlyLoadAppFromAsar: 'OnlyLoadAppFromAsar',
  loadBrowserProcessSpecificV8Snapshot: 'LoadBrowserProcessSpecificV8Snapshot',
  grantFileProtocolExtraPrivileges: 'GrantFileProtocolExtraPrivileges'
}

/**
 * Every configured fuse whose state in `wire` differs, as readable strings.
 * `expected` is the electronFuses config; `wire` maps FuseV1Options index →
 * FuseState (getCurrentFuseWire). An unknown config key is itself a mismatch.
 */
function fuseMismatches(expected, wire, FuseV1Options) {
  const problems = []
  for (const [key, want] of Object.entries(expected || {})) {
    if (NOT_FUSES.has(key) || typeof want !== 'boolean') continue
    const option = FUSE_OPTION[key]
    if (option === undefined) {
      problems.push(`${key}: unknown fuse`)
      continue
    }
    const actual = wire[FuseV1Options[option]]
    const wantState = want ? FUSE_STATE.ENABLE : FUSE_STATE.DISABLE
    if (actual !== wantState) {
      problems.push(`${key}: expected ${want ? 'ENABLE' : 'DISABLE'}, got ${actual}`)
    }
  }
  return problems
}

/** The path @electron/fuses reads: the .app on macOS, the executable elsewhere. */
function electronPath(context) {
  const name = context.packager.appInfo.productFilename
  if (context.electronPlatformName === 'darwin' || context.electronPlatformName === 'mas') {
    return path.join(context.appOutDir, `${name}.app`)
  }
  const exe = context.packager.executableName || name
  return path.join(context.appOutDir, context.electronPlatformName === 'win32' ? `${exe}.exe` : exe)
}

async function afterPack(context) {
  const expected = context.packager.config.electronFuses
  if (expected == null) throw new Error('[verify-fuses] electronFuses is not configured')
  const { getCurrentFuseWire, FuseV1Options } = require('@electron/fuses')
  const fuseConfig = await context.packager.generateFuseConfig(expected)
  await context.packager.addElectronFuses(context, fuseConfig)
  const wire = await getCurrentFuseWire(electronPath(context))
  const problems = fuseMismatches(expected, wire, FuseV1Options)
  if (problems.length > 0) {
    throw new Error(`[verify-fuses] the packed app's fuses do not match: ${problems.join('; ')}`)
  }
  console.log(`[verify-fuses] ${Object.keys(expected).length} fuses verified`)
}

module.exports = afterPack
module.exports.default = afterPack
module.exports.fuseMismatches = fuseMismatches
module.exports.electronPath = electronPath
module.exports.FUSE_STATE = FUSE_STATE
