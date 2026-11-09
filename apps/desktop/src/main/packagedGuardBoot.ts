// ADR-041 amendment 2026-10-28: imported FIRST by index.ts, so the check runs
// before any other module of main evaluates (ES modules evaluate in import
// order). A packaged launch with an argument outside the allowlist (macOS) or
// a remote-debugging / inspector / V8 switch exits at once; the decision itself
// is pure and tested in packagedGuard.ts.
import { app } from 'electron'
import { packagedLaunchRefusal } from './packagedGuard'

const refused = packagedLaunchRefusal({
  isPackaged: app.isPackaged,
  platform: process.platform,
  argv: process.argv,
  hasSwitch: (name) => app.commandLine.hasSwitch(name)
})
if (refused !== null) {
  console.warn(`[solus] refusing to start: ${refused} is not allowed in a packaged build`)
  app.exit(1)
  process.exit(1)
}
