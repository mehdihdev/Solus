// ADR-041 amendment 2026-10-28 (SOLUSDEV-319 drive slice 3b): the drive agent
// trusts any process satisfying Solus.app's code requirement, so a packaged
// Solus.app must only ever run Solus code with Solus configuration. The fuses
// cover ELECTRON_RUN_AS_NODE, NODE_OPTIONS and the Node --inspect flags; this
// refuses the Chromium/V8 switches that would let another process drive main
// (a remote debugger) or change V8's behaviour. Pure; index.ts calls it first.

export const FORBIDDEN_PACKAGED_SWITCHES: readonly string[] = [
  'remote-debugging-port',
  'remote-debugging-pipe',
  'inspect',
  'inspect-brk',
  'inspect-port',
  'js-flags'
]

export interface PackagedGuardInput {
  isPackaged: boolean
  argv: readonly string[]
  /** `app.commandLine.hasSwitch`. */
  hasSwitch(name: string): boolean
}

/** `--name`, `-name`, `--name=…` or `-name=…` (Chromium accepts one dash). */
function argvHasSwitch(argv: readonly string[], name: string): boolean {
  return argv.some((arg) => {
    const bare = arg.replace(/^--?/, '')
    if (bare === arg) return false // not a switch at all
    return bare === name || bare.startsWith(`${name}=`)
  })
}

/** The first forbidden switch present in a packaged launch, or null. */
export function forbiddenPackagedSwitch(input: PackagedGuardInput): string | null {
  if (!input.isPackaged) return null
  return (
    FORBIDDEN_PACKAGED_SWITCHES.find(
      (name) => input.hasSwitch(name) || argvHasSwitch(input.argv, name)
    ) ?? null
  )
}

export interface PackagedLaunchInput extends PackagedGuardInput {
  platform: NodeJS.Platform
}

/** macOS's process serial number argument (older LaunchServices launches). */
const PSN_ARG = /^-psn_\d+_\d+$/
const APP_URL_PREFIX = 'solus://'

/** What to say about a refused argument: a switch's name, never its value. */
function describeArg(arg: string): string {
  if (!arg.startsWith('-')) return 'an unexpected argument'
  return arg.split('=')[0]
}

/** The first argument outside the macOS allowlist (executable, -psn_*, at most
 *  one solus:// URL), described without its value; null when all are allowed. */
function argvAllowlistRefusal(argv: readonly string[]): string | null {
  let urls = 0
  for (const arg of argv.slice(1)) {
    if (PSN_ARG.test(arg)) continue
    if (arg.startsWith(APP_URL_PREFIX) && ++urls === 1) continue
    return describeArg(arg)
  }
  return null
}

/**
 * Review MEDIUM-2: why a packaged launch must not proceed, or null. On macOS
 * — where the drive agent trusts Solus.app's code requirement — argv is an
 * ALLOWLIST: Chromium has many switches that run another program or code
 * inside Solus.app (--browser-subprocess-path, --renderer-cmd-prefix,
 * --gpu-launcher, --utility-cmd-prefix, …), so naming the bad ones cannot be
 * complete. Other packaged platforms (no drive agent; AppImage users pass
 * --no-sandbox) keep the switch denylist. hasSwitch stays as a belt everywhere.
 */
export function packagedLaunchRefusal(input: PackagedLaunchInput): string | null {
  if (!input.isPackaged) return null
  const denied = forbiddenPackagedSwitch(input)
  if (denied !== null) return `--${denied}`
  return input.platform === 'darwin' ? argvAllowlistRefusal(input.argv) : null
}
