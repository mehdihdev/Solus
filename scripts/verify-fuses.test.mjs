// SOLUSDEV-319 drive slice 3b: the fuse read-back used as electron-builder's
// afterPack hook. Run: node --test scripts/verify-fuses.test.mjs
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { fuseMismatches, electronPath, FUSE_STATE: FuseState } = require('./verify-fuses.cjs')
const { FuseV1Options } = require('@electron/fuses')

const EXPECTED = {
  runAsNode: false,
  enableNodeOptionsEnvironmentVariable: false,
  enableNodeCliInspectArguments: false,
  enableEmbeddedAsarIntegrityValidation: true,
  onlyLoadAppFromAsar: true
}

function wireFor(config) {
  const wire = {}
  for (const [key, value] of Object.entries(config)) {
    const option = key[0].toUpperCase() + key.slice(1)
    wire[FuseV1Options[option]] = value ? FuseState.ENABLE : FuseState.DISABLE
  }
  return wire
}

test('a wire matching the config passes', () => {
  assert.deepEqual(fuseMismatches(EXPECTED, wireFor(EXPECTED), FuseV1Options), [])
})

test('a fuse left at its default (runAsNode still on) fails', () => {
  const wire = wireFor({ ...EXPECTED, runAsNode: true })
  const problems = fuseMismatches(EXPECTED, wire, FuseV1Options)
  assert.equal(problems.length, 1)
  assert.match(problems[0], /^runAsNode: expected DISABLE/)
})

test('a fuse missing from the wire fails', () => {
  const wire = wireFor(EXPECTED)
  delete wire[FuseV1Options.OnlyLoadAppFromAsar]
  assert.equal(fuseMismatches(EXPECTED, wire, FuseV1Options).length, 1)
})

test('an unknown fuse key fails; non-boolean options are skipped', () => {
  const problems = fuseMismatches(
    { ...EXPECTED, resetAdHocDarwinSignature: true, notAFuse: true },
    wireFor(EXPECTED),
    FuseV1Options
  )
  assert.deepEqual(problems, ['notAFuse: unknown fuse'])
})

test('reads the .app on macOS and the executable elsewhere', () => {
  const ctx = (platform) => ({
    appOutDir: '/out',
    electronPlatformName: platform,
    packager: { appInfo: { productFilename: 'Solus' }, executableName: 'solus' }
  })
  assert.equal(electronPath(ctx('darwin')), '/out/Solus.app')
  assert.equal(electronPath(ctx('linux')), '/out/solus')
  assert.equal(electronPath(ctx('win32')), '/out/solus.exe')
})

test('the state bytes are ASCII 0 / 1, as @electron/fuses writes them', () => {
  assert.deepEqual(FuseState, { DISABLE: '0'.charCodeAt(0), ENABLE: '1'.charCodeAt(0) })
})
